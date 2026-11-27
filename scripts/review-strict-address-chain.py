#!/usr/bin/env python3
"""Reconcile the address dependency at both memory execution ports of the original model."""
import argparse
from collections import Counter, defaultdict, namedtuple
import json
from pathlib import Path
import runpy
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOAD = runpy.run_path(str(HERE/'review-strict-load-use.py'))
CAP = LOAD['CAP']
PTR, KEY, BR = 0x13ea2, LOAD['RIGHT'], LOAD['BR']
Request = namedtuple('Request', 'tick lane pdst ldq base ea')
Result = namedtuple('Result', 'tick lane pdst ldq value source')


def parse(text):
    requests, results = {}, {}
    for line in text.splitlines():
        row = line.split()
        if (not row or row[0] not in ('A', 'C', 'F') or len(row) != (8 if row[0]=='A' else 7) or
                not all(x.isascii() and x.isdecimal() for x in row[1:])):
            raise ValueError('bad address trace row')
        kind = row[0]; tick, ticket, lane, pdst, ldq, *fields = map(int,row[1:])
        if not (0 < ticket>>7 < tick and lane < 2 and 0 < pdst < 128 and ldq < 32 and all(x < 1<<64 for x in fields)):
            raise ValueError('invalid address event')
        if kind=='A':
            d=requests; value=Request(tick,lane,pdst,ldq,*fields)
        else:
            d=results; value=Result(tick,lane,pdst,ldq,fields[0],kind)
        if ticket in d: raise ValueError('repeated address/result for one allocation')
        d[ticket]=value
    if not requests or requests.keys()!=results.keys(): raise ValueError('unpaired memory request/result')
    return requests,results


def chain(a,p,b,k,ptr_ret,key_ret,previous):
    # Normal low user addresses only, not testing noncanonical address compression or traps.
    if not (p.tick<=ptr_ret and k.tick<=key_ret and a.tick<p.tick<=b.tick<k.tick and
            (a.ldq,a.pdst)==(p.ldq,p.pdst) and (b.ldq,b.pdst)==(k.ldq,k.pdst) and
            a.ea==a.base+8 and b.ea==b.base+2 and max(a.ea,b.ea)<1<<38 and
            a.ea%8==0 and b.ea%2==0 and b.base==p.value and
            (k.tick,k.lane,k.pdst,k.value)==previous):
        raise ValueError('reaching pointer, effective address, queue, operand result or edge mismatch')


def analyse(raw, addr, flow, pcs, expected):
    req,res=parse(addr); prior=LOAD['events'](flow); used=set(); cohorts=defaultdict(lambda:defaultdict(Counter))
    last_operand=defaultdict(Counter); arrivals=defaultdict(Counter)
    def pc(i): return struct.unpack_from('<I',raw['pc'],i*4)[0]
    def entry(i): return struct.unpack_from('<II',raw['tickets'],i*8)
    controls=0
    for i,(cur,) in enumerate(struct.iter_unpack('<I',raw['pc'])):
        if cur!=BR: continue
        start=i-len(pcs)+1
        if start<1 or [pc(j) for j in range(start,i+1)]!=pcs: raise ValueError('different executed block')
        ptr_ret,t1=entry(start); key_ret,t2=entry(start+3); _,br=entry(i)
        if t1 in used or t2 in used or t1==t2 or t1 not in req or t2 not in req: raise ValueError('missing or repeated memory ticket')
        used.update((t1,t2)); a,p,b,k=req[t1],res[t1],req[t2],res[t2]
        br_tick=br>>7; previous=prior['L'][t2]; chain(a,p,b,k,ptr_ret,key_ret,previous)
        if not controls:
            # Wrong base AND adjusted EA still agree locally, but no longer with the real producer.
            for bad in [b._replace(base=b.base+8,ea=b.ea+8), b._replace(ldq=b.ldq^1)]:
                try: chain(a,p,bad,k,ptr_ret,key_ret,previous)
                except ValueError: controls+=1
                else: raise ValueError('corrupted dependency was accepted')
        b2=bool(prior['B'][br][-1]); left_tick=prior['L'][entry(start+1)[1]][0]
        gap=max(left_tick,k.tick)-br_tick
        last_operand['x6' if left_tick>k.tick else 'x28' if k.tick>left_tick else 'tie'][gap]+=1
        arrivals[hex(pc(start-1))+','+hex(PTR)][gap]+=1
        for tag in ['all']+(['x28_last_B2'] if b2 and k.tick>left_tick else []):
            d=cohorts[tag]
            for metric, value in [('ptr_dispatch_to_agu',a.tick-(t1>>7)),('ptr_agu_to_result',p.tick-a.tick),
                    ('ptr_result_to_key_agu',b.tick-p.tick),('key_agu_to_result',k.tick-b.tick),
                    ('key_result_minus_branch_dispatch',k.tick-br_tick),('ptr_agu_to_key_result',k.tick-a.tick)]: d[metric][value]+=1
            d['response_sources'][p.source+k.source]+=1
            d['request_lanes'][str(a.lane)+str(b.lane)]+=1
    if used!=set(req) or len(used)!=2*sum(expected['retired_by_round']) or controls!=2: raise ValueError('incomplete chain coverage')
    if sum(cohorts['x28_last_B2']['request_lanes'].values())!=expected['cohorts']['with_B2']['last_load']['x28']:
        raise ValueError('different branch cohort')
    if {k:sum(v.values()) for k,v in last_operand.items()}!=expected['cohorts']['all']['last_load']:
        raise ValueError('different last-operand cohorts')
    if {k:sum(v.values()) for k,v in arrivals.items()}!=expected['preceding_pc_pairs']:
        raise ValueError('different incoming control flow')
    x28_bound=max(last_operand['x28'])
    tails={src:{'cycles':LOAD['BP']['spread'](v),'over_x28_latest_max':sum(n for g,n in v.items() if g>x28_bound)} for src,v in sorted(last_operand.items())}
    return dict(last_operand_after_branch_dispatch=tails,tail_by_incoming_pc={k:sum(n for g,n in v.items() if g>x28_bound) for k,v in sorted(arrivals.items())},cohorts={tag:{k:(dict(sorted(v.items())) if k in ('request_lanes','response_sources') else LOAD['BP']['spread'](v)) for k,v in d.items()} for tag,d in cohorts.items()})


def review(out,elf):
    sha=CAP['digest']; old=json.loads((ROOT/'docs/perf-strict-load-use.json').read_bytes())
    lock=json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes()); bp=json.loads((ROOT/'docs/perf-strict-redirects.json').read_bytes())
    if sha(elf)!=old['elf_sha256'] or sha(elf)!=lock['elf_sha256']: raise ValueError('wrong guest ELF')
    data=elf.read_bytes(); pcs=[PTR]+LOAD['block'](data)
    if data[PTR-0x10000:PTR-0x10000+2]!=bytes.fromhex('8866') or pcs[3]!=KEY or pcs[-1]!=BR:
        raise ValueError('different compressed pointer load or block')
    manifest=json.loads((out/'inputs.json').read_bytes()); want={**lock['shared_inputs'],**{k:v for k,v in lock['designs']['stock'].items() if k!='model'}}
    for name in ('strict_redirects.hpp','strict_load_use.hpp','strict_address_chain.hpp'):
        if (out/name).read_bytes()!=(ROOT/'tests'/name).read_text().encode(): raise ValueError('wrong probe header')
        want[name]=sha(out/name)
    if (out/'probe.cpp').read_bytes()!=CAP['instrument']((ROOT/'tests/mega_user_replay.cpp').read_text(),True).encode(): raise ValueError('different hooks')
    want.update({k:sha(out/k) for k in ('probe.cpp','model')}); rows={}
    for seed, expected in old['results'].items():
        raw=CAP['checked_capture'](out,seed,bp); sel=out/(seed+'.select'); want[sel.name]=sha(sel)
        if sel.read_bytes()!=CAP['selection'](raw,CAP['PCS']+(PTR,)).encode(): raise ValueError('wrong ticket filter')
        f=out/(seed+'.flow'); af=out/(seed+'.addr')
        if sha(f)!=expected['operand_capture_sha256']: raise ValueError('existing load-to-branch capture changed')
        rows[seed]=dict(**analyse(raw,af.read_text(),f.read_text(),pcs,expected),address_trace_sha256=sha(af),prior_operand_sha256=sha(f))
    if want!=manifest: raise ValueError('different model or probe inputs')
    return dict(scope='User-mode four-round RTL snapshots. C: D-cache response (not necessarily a hit); F: STQ forwarded. AGU observed at core-to-LSU request. Not FPGA performance or a timing improvement.',elf_sha256=sha(elf),probe_model_sha256=want['model'],results=rows)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('out',type=Path); ap.add_argument('elf',type=Path)
    a=ap.parse_args(); print(json.dumps(review(a.out,a.elf),indent=2))
