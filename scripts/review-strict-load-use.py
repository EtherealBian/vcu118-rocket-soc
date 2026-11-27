#!/usr/bin/env python3
"""Certify both inputs at the actual integer compare port, not from a ROB busy/commit proxy."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import runpy
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CAP = runpy.run_path(str(HERE/'test-strict-load-use.py'))
BP = runpy.run_path(str(HERE/'review-strict-redirects.py'))
# Exact retired block, including the two sign-extending LH and every possible intervening write.
WORDS = '00289303 00051603 00251e03 03061393 f0067813 0383d613 00c86633 00c51023 00089603 03061813 f0067513 03885613 8e49 00c89023 07c35063'.split()
LEFT, RIGHT, BR = CAP['PCS']
U64 = 1 << 64


def block(elf):
    ops=[]; pc=LEFT
    for word in WORDS:
        n=len(word)//2
        if elf[pc-0x10000:pc-0x10000+n] != int(word,16).to_bytes(n,'little'):
            raise ValueError('wrong instruction in load-use block')
        ops.append(pc); pc+=n
    return ops


def events(text):
    result={'L':{},'E':{},'B':{}}
    for line in text.splitlines():
        cols=line.split(); k=cols[0] if cols else ''
        if k not in result or len(cols)!=(7 if k=='B' else 6) or not all(x.isascii() and x.isdecimal() for x in cols[1:]):
            raise ValueError('invalid operand capture row')
        tick,key,lane,*tail=map(int,cols[1:]); d=result[k]
        if (key in d or not 0 < (key>>7) < tick or lane >= (2 if k=='L' else 4) or
            (k=='L' and not 0 < tail[0]<128) or any(v>=U64 for v in tail) or
            (k=='B' and (tail[0]!=BR or max(tail[1:])>1))):
            raise ValueError('duplicate or invalid operand event')
        d[key]=(tick,lane,*tail)
    return result


def sample(loads, exe, b1, retire, successor, rd):
    # loads are in x6/x28 architectural source order, not response chronology.
    values=[x[3] for x in loads]; actual=exe[2:]; et,elane=exe[:2]; bt,blane,pc,taken,miss=b1
    if values!=list(actual) or any(((v+32768)%65536-32768)%U64!=v for v in values):
        raise ValueError('integer load data does not match sign-extended ALU operands')
    signed=[v-U64 if v>>63 else v for v in values]
    if (loads[0][2]==loads[1][2] or pc!=BR or successor!=(0x13f3a if signed[0]>=signed[1] else BR+4) or
        bool(taken)!=(successor==0x13f3a) or elane!=blane or bt!=et+1 or et>retire or bool(rd)!=bool(miss) or
        (rd and (rd[0]!=bt+1 or rd[1:]!=(BR,successor,BP['BR'],taken,4)))):
        raise ValueError('branch request, registered B1, B2 or architectural successor mismatch')
    return max(x[0] for x in loads)


def analyse(raw, trace, seq, window, baseline):
    flow=events(trace); red=BP['redirects'](raw['redirects'].decode(),window)
    n=len(raw['pc'])//4; round_no=0; previous=Counter(); by_round=[0]*4; red_round=[0]*4
    def pc(i): return struct.unpack_from('<I',raw['pc'],4*i)[0]
    def entry(i): return struct.unpack_from('<II',raw['tickets'],8*i)
    buckets=defaultdict(lambda:defaultdict(Counter)); used={k:set() for k in flow}; mutation=None
    for i,(p,) in enumerate(struct.iter_unpack('<I',raw['pc'])):
        if p==BP['PROFILE']['NEXT']: round_no+=1
        if p!=BR: continue
        first=i+1-len(seq)
        if first<2 or i+1>=n or not 0<=round_no<4 or [pc(j) for j in range(first,i+1)]!=seq:
            raise ValueError('other dynamic reaching definition or incomplete block')
        previous[hex(pc(first-2))+','+hex(pc(first-1))]+=1
        ti,branch=entry(i); pair=[entry(first),entry(first+2)]
        def get(k,t):
            if t not in flow[k] or t in used[k]: raise ValueError('missing or reused dynamic event')
            used[k].add(t); return flow[k][t]
        loads=[get('L',t) for _,t in pair]; exe=get('E',branch); b1=get('B',branch); rd=red.get(branch)
        if any(obs[0]>tick for obs,(tick,_) in zip(loads,pair)):
            raise ValueError('load result after retirement')
        suc=pc(i+1); last=sample(loads,exe,b1,ti,suc,rd)
        if rd and mutation is None: mutation=(loads,exe,b1,ti,suc,rd)
        by_round[round_no]+=1; red_round[round_no]+=bool(rd)
        for bucket in ('all', 'with_B2' if rd else 'without_B2'):
            hist=buckets[bucket]; gap=last-(branch>>7)
            for tag,val in [('later_load_minus_dispatch',gap),('alu_input_minus_later_load',exe[0]-last),
                            ('registered_B1_minus_alu_input',b1[0]-exe[0])]: hist[tag][val]+=1
            hist['alu_gap_distribution'][str(exe[0]-last)]+=1
            hist['last_load']['same_edge' if loads[0][0]==loads[1][0] else ('x6' if loads[0][0]>loads[1][0] else 'x28')]+=1
            hist['last_relative_to_dispatch']['before' if gap<0 else 'after' if gap>0 else 'same_edge']+=1
    top=baseline['top10_by_matched'][0]
    if (top['pc']!=hex(BR) or sum(by_round)!=top['retired'] or red_round!=top['by_round'] or
        any(used[k]!=set(flow[k]) for k in used) or mutation is None): raise ValueError('incomplete coverage')
    # Change bits on *real* rows. A changed operand may leave direction unchanged: check the exact value.
    loads,exe,b1,ti,suc,rd=mutation
    corruptions=[([(*loads[0][:3],loads[0][3]^1),loads[1]],exe,b1,ti,suc,rd),
                 (loads,exe,(b1[0]+1,*b1[1:]),ti,suc,rd)]
    for case in corruptions:
        try: sample(*case)
        except ValueError: pass
        else: raise ValueError('corrupt operand or edge was accepted')
    return dict(retired_by_round=by_round,redirects_by_round=red_round,preceding_pc_pairs=dict(sorted(previous.items())),
                cohorts={k:{name:(dict(v) if name in ('last_load','last_relative_to_dispatch','alu_gap_distribution') else BP['spread'](v))
                            for name,v in h.items()} for k,h in buckets.items()},
                private_trace_controls=['operand_bit_flip_rejected','B1_edge_shift_rejected'])


def review(out,elf):
    oracle=json.loads((ROOT/'docs/perf-strict-redirects.json').read_bytes())
    lock=json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes()); sha=CAP['digest']
    if sha(elf)!=oracle['elf_sha256'] or sha(elf)!=lock['elf_sha256']: raise ValueError('wrong program')
    seq=block(elf.read_bytes()); inputs=json.loads((out/'inputs.json').read_bytes()); rows={}
    want={**lock['shared_inputs'],**{k:v for k,v in lock['designs']['stock'].items() if k!='model'}}
    for k in ('model','probe.cpp','strict_redirects.hpp','strict_load_use.hpp','performance.select','validation.select'):
        want[k]=sha(out/k)
    if want!=inputs or any((out/k).read_text()!=(ROOT/'tests'/k).read_text() for k in ('strict_redirects.hpp','strict_load_use.hpp')):
        raise ValueError('wrong model or instrumentation manifest')
    if (out/'probe.cpp').read_bytes()!=CAP['instrument']((ROOT/'tests/mega_user_replay.cpp').read_text()).encode():
        raise ValueError('wrong probe hooks')
    for seed,baseline in oracle['results'].items():
        raw=CAP['checked_capture'](out,seed,oracle)
        if (out/(seed+'.select')).read_bytes()!=CAP['selection'](raw).encode(): raise ValueError('wrong observation filter')
        f=out/(seed+'.flow'); rows[seed]=dict(analyse(raw,f.read_text(),seq,lock['matched_windows'][seed],baseline),
                                                operand_capture_sha256=sha(f),reference_capture_sha256=baseline['sha256'])
    return dict(scope='Original four-wide BOOM, two four-round user-mode RTL snapshot replays; integer load result ports, branch ALU input values and registered B1. Not a DDR latency, cycle savings estimate or board score.',elf_sha256=sha(elf),probe_model_sha256=inputs['model'],results=rows)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('run',type=Path);ap.add_argument('elf',type=Path)
    a=ap.parse_args(); print(json.dumps(review(a.run,a.elf),indent=2))
