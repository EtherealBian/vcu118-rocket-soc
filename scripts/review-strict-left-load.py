#!/usr/bin/env python3
"""Partition the x6 wait at the AGU, qualifying normal D-cache port attempts by lane handshake."""
import argparse
from collections import Counter, defaultdict, namedtuple
import json
from pathlib import Path
import runpy
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ADDR = runpy.run_path(str(HERE/'review-strict-address-chain.py'))
LOAD, CAP = ADDR['LOAD'], ADDR['CAP']
PARENT, LEFT, RIGHT, BR = 0x13e9e, LOAD['LEFT'], LOAD['RIGHT'], LOAD['BR']
Event = namedtuple('Event', 'kind tick lane q d v x')


def parse(text):
    rows = defaultdict(list); occupied=set(); last=0
    for line in text.splitlines():
        c = line.split()
        if len(c)!=8 or c[0] not in ('A','S','T','C','F') or not all(x.isascii() and x.isdecimal() for x in c[1:]):
            raise ValueError('invalid left trace row')
        k = c[0]; tick,key,lane,q,d,v,x = map(int,c[1:])
        if not (0 < key>>7 < tick and lane<2 and q<32 and 0<d<128 and v<1<<64 and x<1<<64):
            raise ValueError('left trace field out of range')
        if (k in 'SC' and x!=0) or (k=='T' and x>3) or (k=='F' and x>=32):
            raise ValueError('invalid cache metadata')
        port=(tick,'R' if k in 'CF' else k,lane)
        if tick<last or port in occupied: raise ValueError('reused physical port or nonmonotonic trace')
        occupied.add(port); last=tick
        rows[key].append(Event(k,tick,lane,q,d,v,x))
    return rows


def inspect(rows, offset, retired):
    agu=[e for e in rows if e.kind=='A']; result=[e for e in rows if e.kind in 'CF']
    if len(agu)!=1 or len(result)!=1: raise ValueError('expected one AGU and one result')
    a, r=agu[0], result[0]; s1={}; s2={}
    if not (a.x==a.v+offset and a.x<1<<38 and a.x%offset==0 and a.tick<r.tick<=retired):
        raise ValueError('bad effective address or return')
    for e in rows:
        if (e.d,e.q)!=(a.d,a.q) or not a.tick<=e.tick<=r.tick: raise ValueError('changed identity or edge')
        if e.kind not in 'ST': continue
        if e.v>>40 or (e.v^a.x)&4095: raise ValueError('wrong translated page offset')
        key=(e.tick-(1 if e.kind=='S' else 2),e.lane)
        m=s1 if e.kind=='S' else s2
        if key in m or key[0]<a.tick: raise ValueError('duplicate or premature normal cache attempt')
        m[key]=e
    if any(k not in s1 or s1[k].v!=e.v for k,e in s2.items()): raise ValueError('S2 without corresponding accepted S1 lane/address')
    # A bank conflict can produce a nack even if hit is asserted: keep both bits.
    path=Counter('no_s2' if k not in s2 else ('nack_hit' if s2[k].x==3 else 'nack_miss' if s2[k].x==2 else 'hit' if s2[k].x==1 else 'miss') for k in s1)
    return a,r,path


def result_class(rows, r):
    if r.kind=='F': return 'store_queue'
    return ('same_lane_normal_s2_hit' if any(e.kind=='T' and e.x==1 and (e.tick,e.lane)==(r.tick,r.lane) for e in rows) else 'other_cache_response')


def reaching(pr, a):
    if pr.tick>a.tick or pr.v!=a.v: raise ValueError('different reaching pointer')


def analyse(raw, text, flow_text, seq, ref):
    trace=parse(text); loads=LOAD['events'](flow_text)['L']; used=set(); h=defaultdict(lambda:defaultdict(Counter)); route=Counter()
    def pc(i): return struct.unpack_from('<I',raw['pc'],i*4)[0]
    def ticket(i): return struct.unpack_from('<II',raw['tickets'],i*8)
    def at(i,offset):
        rt,key=ticket(i)
        if key in used or key not in trace: raise ValueError('missing or reused load')
        used.add(key); return inspect(trace[key],offset,rt)
    for i,(cur,) in enumerate(struct.iter_unpack('<I',raw['pc'])):
        if cur!=BR: continue
        j=i-len(seq)+1
        if j<2 or [pc(x) for x in range(j,i+1)]!=seq or pc(j-1)!=ADDR['PTR'] or pc(j-2) not in (PARENT,0x13f50):
            raise ValueError('different executed compare path')
        _,lk=ticket(j); _,rk=ticket(j+2); _,bk=ticket(i)
        a,r,attempts=at(j,2); rr=loads[rk][0]; bd=bk>>7
        if (r.tick,r.lane,r.d,r.v)!=loads[lk]: raise ValueError('changed independently observed branch operand')
        fall=pc(j-2)==PARENT; parent=at(j-2,8) if fall else None
        if parent: reaching(parent[1],a)
        bound=ref['last_operand_after_branch_dispatch']['x28']['cycles']['max']; tail=max(r.tick,rr)-bd>bound
        if tail and r.tick<=rr: raise ValueError('changed last-operand cohort')
        cohort='tail_fallthrough' if fall else 'tail_jump'
        if tail: route[hex(pc(j-2))+','+hex(ADDR['PTR'])]+=1
        for tag in (['all',cohort] if tail else ['all']):
            d=h[tag]; d['above_bound_wait_cycles']['sum']+=max(0,r.tick-bd-bound); d['loads'][r.kind]+=1; d['return_observation'][result_class(trace[lk],r)]+=1; d['normal_port_outcomes'].update(attempts)
            d['normal_accepts'][sum(attempts.values())]+=1
            for name,value in [('dispatch_to_agu',a.tick-(lk>>7)),('agu_minus_branch_dispatch',a.tick-bd),('agu_to_result',r.tick-a.tick),('result_minus_branch_dispatch',r.tick-bd)]:
                d[name][value]+=1
            if parent:
                pa,pr,pp=parent
                d['parent_dispatch_to_agu'][pa.tick-(ticket(j-2)[1]>>7)]+=1
                d['parent_agu_minus_branch_dispatch'][pa.tick-bd]+=1
                d['parent_agu_to_result'][pr.tick-pa.tick]+=1
                d['parent_result_to_left_agu'][a.tick-pr.tick]+=1
                d['parent_sources'][pr.kind]+=1
                d['parent_normal_port_outcomes'].update(pp)
    if used!=set(trace) or dict(route)!=ref['tail_by_incoming_pc'] or sum(h['all']['loads'].values())!=sum(s['cycles']['n'] for s in ref['last_operand_after_branch_dispatch'].values()):
        raise ValueError('incomplete retired-ticket or tail coverage')
    categorical={'above_bound_wait_cycles','loads','normal_accepts','return_observation','normal_port_outcomes','parent_sources','parent_normal_port_outcomes'}
    spread=LOAD['BP']['spread']
    return {tag:{k:(dict(sorted(v.items())) if k in categorical else spread(v)) for k,v in d.items()} for tag,d in h.items()}


def review(out,elf):
    sha=CAP['digest']; lock=json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes()); prev=json.loads((ROOT/'docs/perf-strict-address-chain.json').read_bytes()); bp=json.loads((ROOT/'docs/perf-strict-redirects.json').read_bytes())
    if sha(elf)!=prev['elf_sha256'] or sha(elf)!=lock['elf_sha256']: raise ValueError('wrong benchmark ELF')
    data=elf.read_bytes(); seq=LOAD['block'](data)
    if data[PARENT-0x10000:LEFT-0x10000]!=bytes.fromhex('833884008866'): raise ValueError('different parent / pointer instructions')
    want={**lock['shared_inputs'],**{k:v for k,v in lock['designs']['stock'].items() if k!='model'}}
    for name in ('strict_redirects.hpp','strict_load_use.hpp','strict_address_chain.hpp','strict_left_load.hpp'):
        if (out/name).read_bytes()!=(ROOT/'tests'/name).read_text().encode(): raise ValueError('unexpected probe '+name)
        want[name]=sha(out/name)
    cpp=out/'probe.cpp'; want['probe.cpp']=sha(cpp); want['model']=sha(out/'model')
    if cpp.read_bytes()!=CAP['instrument']((ROOT/'tests/mega_user_replay.cpp').read_text(),True,True).encode(): raise ValueError('unexpected model hooks')
    results={}
    for seed,ref in prev['results'].items():
        raw=CAP['checked_capture'](out,seed,bp); sel=out/(seed+'.select'); want[sel.name]=sha(sel)
        if sel.read_bytes()!=CAP['selection'](raw,CAP['PCS']+(ADDR['PTR'],PARENT)).encode(): raise ValueError('wrong ticket filter')
        f=out/(seed+'.flow'); af=out/(seed+'.addr'); left=out/(seed+'.left')
        if sha(f)!=ref['prior_operand_sha256'] or sha(af)!=ref['address_trace_sha256']: raise ValueError('existing operand/address traces changed')
        results[seed]=dict(left_sha256=sha(left),cohorts=analyse(raw,left.read_text(),f.read_text(),seq,ref))
    if want!=json.loads((out/'inputs.json').read_bytes()): raise ValueError('wrong probe/model manifest')
    return dict(scope='Four-round user-mode RTL snapshots; normal LSU-to-cache lane handshakes confirmed at S1; only normal S2 shown, not internal MSHR replays. C: cache result; F: store queue. Not board timing or throughput.',elf_sha256=sha(elf),probe_model_sha256=want['model'],results=results)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('run',type=Path); ap.add_argument('elf',type=Path)
    a=ap.parse_args(); print(json.dumps(review(a.run,a.elf),indent=2))
