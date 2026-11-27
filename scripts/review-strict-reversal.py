#!/usr/bin/env python3
"""Bind the reversal recurrence to actual load values, execution, busy flags and retirement."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import runpy
import struct

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT/'scripts/review-strict-rob-heads.py'))
BP, CAP, LOOP = H['BP'], H['CAP'], H['LOOP']
BR, ENTRY = LOOP[-1], 0x13b60


def flow(text):
    rows = {k:{} for k in 'ALMEBW'}
    prev = 0
    for ln in text.splitlines():
        cols=ln.split(); kind=cols[0] if cols else ''
        if kind not in rows or len(cols)!=6 or not all(x.isascii() and x.isdecimal() for x in cols[1:]):
            raise ValueError('malformed reversal event')
        t,key,lane,a,b=map(int,cols[1:])
        if (t<prev or not 0 < key>>7 < t or key>=1<<32 or key in rows[kind] or
            lane>=(2 if kind in 'AL' else 4) or max(a,b)>=1<<64 or
            (kind=='L' and b>1) or (kind=='B' and max(a,b)>1) or
            (kind=='W' and (a or b or lane!=key%4))):
            raise ValueError('invalid, unordered or repeated reversal event')
        rows[kind][key]=(t,lane,a,b); prev=t
    return rows


def one_branch(a,l,e,b,w,retire,taken,redirect):
    if (a[2]!=a[3] or not a[2] or a[2]%8 or not a[0]<l[0] or e[2:]!=(l[2],0) or
        not l[0]<=e[0] or e[1]!=b[1] or b[0]!=e[0]+1 or b[2]!=taken or bool(l[2])!=taken or
        bool(redirect)!=bool(b[3]) or (redirect and redirect!=(b[0]+1,BR,LOOP[0] if taken else BR+2,BP['BR'],int(taken),2)) or
        not e[0]<w[0]<=retire):
        raise ValueError('wrong load/branch value, identity, direction or edge')


def recurrence(l,m,a,next_l):
    # The locked c.mv expands to add x8,x0,x14. Same value must actually reach
    # rs2 at the move and the base and effective address at the following load.
    if (not l[2] or m[2:]!=(0,l[2]) or a[2:]!=(l[2],l[2]) or
        not l[0]<=m[0]<a[0]<next_l[0]):
        raise ValueError('broken loop-carried load -> move -> address -> load chain')
    return (m[0]-l[0],a[0]-m[0],next_l[0]-a[0])


def summarize(hist):
    return dict(**BP['spread'](hist),histogram=dict(sorted(hist.items())))


def analyse(raw,text,head_bytes,redirects,base):
    rows=flow(text); used={k:set() for k in rows}; n=len(raw['pc'])//4
    def pc(i): return BP['PC'].unpack_from(raw['pc'],4*i)[0]
    def ticket(i): return BP['TICKET'].unpack_from(raw['tickets'],8*i)
    def get(kind,key):
        if key not in rows[kind] or key in used[kind]: raise ValueError('missing or reused '+kind+' event')
        used[kind].add(key); return rows[kind][key]
    hist=defaultdict(Counter); amount=Counter(); phases=Counter(); branches={}; previous=None
    for i,(p,) in enumerate(BP['PC'].iter_unpack(raw['pc'])):
        if p!=BR: continue
        if not 4<=i<n-1 or tuple(pc(j) for j in range(i-3,i+1))!=LOOP[1:]:
            raise ValueError('wrong reaching load or incomplete branch')
        rt,br=ticket(i); lt,load=ticket(i-3)
        a=get('A',load); l=get('L',load); e=get('E',br); b=get('B',br); w=get('W',br)
        suc=pc(i+1); taken=suc==LOOP[0]
        if not (taken or suc==BR+2) or l[0]>lt: raise ValueError('wrong successor or late load')
        one_branch(a,l,e,b,w,rt,taken,redirects.get(br))
        branches[br]=(l[0],e[0],w[0]); amount['branches']+=1; amount['taken' if taken else 'exits']+=1
        amount['dcache' if l[3] else 'store_queue']+=1
        for name,delta in [('address_to_result',l[0]-a[0]),('result_to_branch_execute',e[0]-l[0]),
                           ('branch_execute_to_busy_clear',w[0]-e[0]),('busy_clear_to_retire',rt-w[0])]: hist[name][delta]+=1
        if pc(i-4)==LOOP[0]:
            if previous is None or previous[0]!=i-5 or not previous[1]: raise ValueError('no previous taken branch')
            mt,mov=ticket(i-4); m=get('M',mov)
            if m[0]>mt: raise ValueError('move execution after retirement')
            gaps=recurrence(previous[2],m,a,l)
            group=(mov>>7)==(load>>7); amount['same_dispatch' if group else 'separate_dispatch']+=1
            if group and (load!=mov+1 or load//4!=mov//4): raise ValueError('not adjacent lanes in same dispatch row')
            for name,delta in zip(('prev_result_to_move','move_to_next_address','next_address_to_next_result'),gaps): hist[name][delta]+=1
            if gaps==(2,1,2):
                amount['two_one_two']+=1
                if group: amount['same_dispatch_two_one_two']+=1
            hist['load_to_load'][sum(gaps)]+=1
            hist['load_to_load_same_dispatch' if group else 'load_to_load_separate_dispatch'][sum(gaps)]+=1
        elif pc(i-4)!=ENTRY or (previous is not None and previous[1]): raise ValueError('invalid reversal entry')
        previous=(i,taken,l)
    if previous is None or previous[1] or any(used[k]!=rows[k].keys() for k in rows):
        raise ValueError('unfinished loop or orphan capture events')
    for t,k,word in H['HEAD'].iter_unpack(head_bytes):
        if k not in branches or H['gate'](t,k,word)!='busy': continue
        lt,et,wt=branches[k]
        if t>=wt: raise ValueError('busy head at or after observed clear')
        phases['before_load_result' if t<lt else 'from_result_before_execute' if t<et else 'from_execute_before_clear']+=1
    exp=base['reversal_loop']; top=base['top_busy_heads'][0]
    if (top['pc']!=hex(BR) or amount['branches']!=top['retirements'] or amount['taken']!=exp['taken'] or
        sum(hist['load_to_load'].values())!=amount['taken'] or amount['exits']!=exp['fallthrough'] or
        sum(phases.values())!=top['oldest_busy_edges']): raise ValueError('mismatch with locked ROB census')
    return dict(counts=dict(sorted(amount.items())),busy_head_edges_by_observed_phase={k:phases[k] for k in ('before_load_result','from_result_before_execute','from_execute_before_clear')},
                cycle_intervals={k:summarize(v) for k,v in sorted(hist.items())})


def review(out,heads,elf):
    def doc(name): return json.loads((ROOT/'docs'/name).read_bytes())
    prior=doc('perf-strict-redirects.json'); head_ref=doc('perf-strict-rob-heads.json'); lock=doc('perf-strict-user-lvt.json')
    code=elf.read_bytes(); sha=CAP['digest']; ref=doc('perf-strict-user-window.json')
    if (sha256(code).hexdigest()!=ref['elf_sha256'] or code[LOOP[0]-0x10000:BR-0x10000+2]!=bytes.fromhex('3a84186014e0a28665ff')):
        raise ValueError('different ELF or loop encoding')
    inputs=json.loads((out/'inputs.json').read_bytes()); want={**lock['shared_inputs'],**{k:v for k,v in lock['designs']['stock'].items() if k!='model'}}
    for name in ('strict_redirects.hpp','strict_reversal.hpp'):
        if (out/name).read_bytes()!=(ROOT/'tests'/name).read_text().encode(): raise ValueError('wrong probes')
    if (out/'probe.cpp').read_bytes()!=CAP['reversal_probe']((ROOT/'tests/mega_user_replay.cpp').read_text()).encode(): raise ValueError('wrong hooks')
    for k in ('strict_redirects.hpp','strict_reversal.hpp','probe.cpp','model','performance.select','validation.select'): want[k]=sha(out/k)
    if inputs!=want: raise ValueError('model input mismatch')
    result={}
    for seed,base in head_ref['results'].items():
        raw=CAP['checked_capture'](out,seed,prior); h=(heads/(seed+'.heads')).read_bytes()
        if sha256(h).hexdigest()!=base['head_capture_sha256'] or (out/(seed+'.select')).read_bytes()!=CAP['selection'](raw,CAP['REVERSAL_PCS']).encode():
            raise ValueError('wrong prior head capture or selected tickets')
        window=BP['REPLAY']['inspect'](raw['events'].decode(),raw['uart'],raw['pc'],ref['results'][seed],include_widths=True)
        if window!=lock['matched_windows'][seed]: raise ValueError('unexpected hot window')
        path=out/(seed+'.reversal'); result[seed]=dict(**analyse(raw,path.read_text(),h,BP['redirects'](raw['redirects'].decode(),window),base),
                                                      reversal_sha256=sha(path),head_sha256=base['head_capture_sha256'])
    return dict(scope='Unchanged four-wide BOOM; four rounds per seed from user snapshots. Observed operand/ROB edges, not cycle savings, physical timing or FPGA scores.',
                elf_sha256=ref['elf_sha256'],probe_sha256=inputs['strict_reversal.hpp'],model_sha256=inputs['model'],results=result)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('capture','prior_heads','elf'): ap.add_argument(name,type=Path)
    a=ap.parse_args(); print(json.dumps(review(a.capture,a.prior_heads,a.elf),indent=2))
