#!/usr/bin/env python3
"""Join every zero-retirement edge strictly between the two hot-PC fences to the actual head."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import runpy
import struct

ROOT = Path(__file__).resolve().parents[1]
CAP = runpy.run_path(str(ROOT/'scripts/test-strict-load-use.py'))
BP = runpy.run_path(str(ROOT/'scripts/review-strict-redirects.py'))
HEAD = struct.Struct('<III')


def gate(tick, key, word):
    row = word & 31
    valid, busy, exc, commits = ((word >> b) & 15 for b in (5, 9, 13, 17))
    csr, block = bool(word & (1<<21)), bool(word & (1<<22))
    if word >> 23 or (busy|exc) & ~valid or bool(key) != bool(valid):
        raise ValueError('invalid head masks')
    first = valid & -valid
    if valid and (key & 127 != row*4+first.bit_length()-1 or not 0 < key>>7 < tick):
        raise ValueError('head not an earlier allocation at the oldest valid slot')
    expected = 0
    for i in (1,2,4,8):
        if valid & i:
            if block or csr or (busy|exc) & i:
                break
            expected |= i
    if expected != commits:
        raise ValueError('bad head gate reconstruction')
    if not valid:
        return 'no_valid_head_lane'
    if commits:
        return 'nonarchitectural_commit'
    reasons = [name for on, name in [(block,'global'),(csr,'csr'),(first&exc,'exception'),(first&busy,'busy')] if on]
    if not reasons:
        raise ValueError('unexplained head stop')
    return '+'.join(reasons)


def census(pcs, tickets, heads, redirects, fences):
    if not pcs or len(pcs)%4 or len(tickets)!=2*len(pcs) or len(heads)%HEAD.size:
        raise ValueError('unpaired or incomplete trace')
    samples=HEAD.iter_unpack(heads); prev=fences[0]; active_edges=0; per=defaultdict(Counter)
    classes=Counter(); age=Counter(); last_slot=-1; last_alloc=0; generation=[0]*128
    for (pc,),(tick,key) in zip(BP['PC'].iter_unpack(pcs), BP['TICKET'].iter_unpack(tickets)):
        slot, alloc=key&127,key>>7
        if (not 0<alloc<tick or alloc<last_alloc or generation[slot]>=alloc or not prev<=tick<=fences[-1] or
                (not active_edges and tick!=prev) or (prev==tick and last_slot>=0 and (slot<=last_slot or slot//4!=last_slot//4))):
            raise ValueError('out-of-order allocation or retirement')
        c=per[pc]; c['retirements']+=1
        mispredict=key in redirects
        if mispredict and redirects[key][1]!=pc:
            raise ValueError('redirect belongs to different PC')
        c['own_b2']+=int(mispredict)
        for missing in range(prev+1,tick):
            rec=next(samples,None)
            if rec is None or rec[0]!=missing:
                raise ValueError('head samples do not exactly cover every idle edge')
            _,head,word=rec; cause=gate(missing,head,word)
            if head and (head>>7 <= generation[head&127] or
                         (head&127==slot and alloc<missing and head!=key)):
                raise ValueError('retired or superseded head allocation')
            classes[cause]+=1
            age['previously_dispatched' if alloc<missing else 'not_previously_dispatched']+=1
            if cause=='busy' and head==key:
                c['oldest_busy_edges']+=1
                if mispredict: c['oldest_busy_edges_with_own_b2']+=1
            elif cause=='busy':
                c['different_busy_head_edges']+=1
            c['preceding_idle_edges']+=1
        if tick!=prev or not active_edges: active_edges+=1
        generation[slot]=last_alloc=alloc; last_slot=slot; prev=tick
    if prev!=fences[-1] or next(samples,None) is not None or sum(classes.values())+active_edges!=prev-fences[0]+1:
        raise ValueError('unreconciled fence span or trailing head sample')
    # First and last fences both carry a hot commit in these two snapshots. The
    # duration is their difference; do not count both endpoints toward that duration.
    ranked=sorted(per,key=lambda pc:(-per[pc]['oldest_busy_edges'],pc))
    def report(pc):
        return dict(pc=hex(pc), **{k:per[pc][k] for k in ('retirements','own_b2','preceding_idle_edges','oldest_busy_edges','oldest_busy_edges_with_own_b2')})
    return dict(hot_cycle_span=prev-fences[0], idle_edges=sum(classes.values()),
                head_gate_counts=dict(sorted(classes.items())),next_instruction_dispatch= dict(sorted(age.items())),
                next_ticket_is_busy_head=sum(c['oldest_busy_edges'] for c in per.values()),
                other_ticket_is_busy_head=sum(c['different_busy_head_edges'] for c in per.values()),
                top_busy_heads=[report(pc) for pc in ranked[:8]], compare_branch=report(0x13eda))


# Linked-list reversal body in the locked ELF: mv; ld; sd; mv; bnez(back).
LOOP=(0x13b62,0x13b64,0x13b66,0x13b68,0x13b6a)


def loop_intervals(pcs,tickets,b2):
    commits,dispatches=Counter(),Counter(); exits=taken_b2=0
    for i,(pc,) in enumerate(BP['PC'].iter_unpack(pcs)):
        if pc!=LOOP[-1]:continue
        if 4*(i+2)>len(pcs):raise ValueError('unterminated loop branch')
        nxt,=BP['PC'].unpack_from(pcs,4*(i+1))
        if nxt==pc+2:
            exits+=1; continue
        if 4*(i+6)>len(pcs) or struct.unpack_from('<5I',pcs,4*(i+1))!=LOOP:
            raise ValueError('not the consecutive taken reversal body')
        begin,start_key=BP['TICKET'].unpack_from(tickets,8*i)
        end,end_key=BP['TICKET'].unpack_from(tickets,8*(i+5))
        if end<=begin or end_key>>7 <= start_key>>7:raise ValueError('invalid five-instruction loop interval')
        commits[end-begin]+=1; dispatches[(end_key>>7)-(start_key>>7)]+=1
        taken_b2+=start_key in b2
    if not commits or not exits:raise ValueError('missing taken or exit cohort')
    def describe(hist):return dict(**BP['spread'](hist),sum_cycles=sum(g*n for g,n in hist.items()),exactly_five=hist[5])
    return dict(taken=sum(commits.values()),fallthrough=exits,taken_with_own_b2=taken_b2,
                branch_to_branch_retirement=describe(commits),branch_to_branch_dispatch=describe(dispatches))


def review(out,elf):
    def doc(name):return json.loads((ROOT/'docs'/name).read_bytes())
    lock=doc('perf-strict-user-lvt.json'); prior=doc('perf-strict-redirects.json'); ref=doc('perf-strict-user-window.json')
    inputs=json.loads((out/'inputs.json').read_bytes()); expected={**lock['shared_inputs'],**{k:v for k,v in lock['designs']['stock'].items() if k!='model'}}
    for k in ('strict_redirects.hpp','strict_rob_heads.hpp'):
        if (out/k).read_bytes()!=(ROOT/'tests'/k).read_text().encode():raise ValueError('different head/dispatch probe')
    if (out/'probe.cpp').read_bytes()!=CAP['head_probe']((ROOT/'tests/mega_user_replay.cpp').read_text()).encode():raise ValueError('changed probe hooks')
    expected.update({k:CAP['digest'](out/k) for k in ('strict_redirects.hpp','strict_rob_heads.hpp','probe.cpp','model')})
    if inputs!=expected:raise ValueError('different model or probe inputs')
    code=elf.read_bytes()
    if sha256(code).hexdigest()!=ref['elf_sha256'] or code[LOOP[0]-0x10000:LOOP[-1]-0x10000+2]!=bytes.fromhex('3a84186014e0a28665ff'):
        raise ValueError('different strict ELF or loop instructions')
    rows={}
    for seed in ('performance','validation'):
        raw=CAP['checked_capture'](out,seed,prior)
        w=BP['REPLAY']['inspect'](raw['events'].decode(),raw['uart'],raw['pc'],ref['results'][seed],include_widths=True)
        if w!=lock['matched_windows'][seed]:raise ValueError('not the original window')
        b2=BP['redirects'](raw['redirects'].decode(),w); h=(out/(seed+'.heads')).read_bytes()
        rows[seed]=dict(**census(raw['pc'],raw['tickets'],h,b2,w['fence_ticks']),head_capture_sha256=sha256(h).hexdigest(),
                        tickets_sha256=prior['results'][seed]['sha256']['tickets'],
                        reversal_loop=loop_intervals(raw['pc'],raw['tickets'],b2))
    return dict(scope='Four rounds in each user-mode RTL snapshot, stock BOOM. Oldest ROB busy is a retirement gate, not the underlying execution cause or removable latency. Not full Linux, physical timing or board throughput.',
                elf_sha256=ref['elf_sha256'],model_sha256=inputs['model'],probe_source_sha256=inputs['probe.cpp'],
                head_probe_sha256=inputs['strict_rob_heads.hpp'],results=rows)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path)
    p.add_argument('elf',type=Path); a=p.parse_args()
    print(json.dumps(review(a.capture,a.elf),indent=2))
