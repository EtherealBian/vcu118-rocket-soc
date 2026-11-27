#!/usr/bin/env python3
"""Reconcile both 40-slot registered cone routes and all 159 paths per variant."""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import runpy

common=runpy.run_path(str(Path(__file__).with_name('review-mega-loop-ooc.py')))
need,single,digest=(common[k] for k in ('need','single','digest'))


def collect(proof, pair, console):
    q=json.loads((proof/'result.json').read_bytes())
    hashes={k:digest(proof/k) for k in ('stock.v','candidate.v','boundary.v','clock.xdc')}
    need(hashes==q['cone_sha256'] and q['sat']=={'candidate':'equivalent','cross_slot9':'counterexample','omit_p2_poison':'counterexample'},'unproved input')
    log=console.read_text(errors='replace');markers=[s for s in log.splitlines() if s.startswith('INT_MISS_OOC_')]
    need(markers==['INT_MISS_OOC_CASE_COLLECTED stock','INT_MISS_OOC_CASE_COLLECTED candidate','INT_MISS_OOC_PAIR_COLLECTED_NOT_SOC'] and not re.search(r'^ERROR:',log,re.M),'incomplete Vivado run')
    result={}; endpoints={}
    for name in ('stock','candidate'):
        d=pair/name;route,timing,util=[(d/n).read_text() for n in ('route.rpt','timing.rpt','util.rpt')]
        for t in (timing,util):
            for key,value in [('Design','miss_boundary'),('Design State','Routed')]:
                need(single(r'^\| '+key+r'\s*:\s*(\S+)\s*$',t)==value,'wrong design')
        need(single(r'^\| Device\s*:\s*(\S+)\s*$',util)=='xcvu9p-flga2104-2L-e' and 'Vivado v.2024.2' in timing and re.search(r'^cpu\s+\{0\.000 2\.857\}\s+5\.714\s',timing,re.M),'wrong timing context')
        counts=[int(single(r'# of '+k+r'\.+\s*:\s*(\d+)\s*:',route)) for k in ('routable nets','fully routed nets','nets with routing errors')]
        need(counts[0]==counts[1]>0 and counts[2]==0,'incomplete route')
        sta=single(r'^cpu\s+(-?[\d.]+(?:\s+-?[\d.]+){11})\s*$',timing).split()
        with (d/'paths.tsv').open(newline='') as f:
            r=csv.DictReader(f,delimiter='\t');rows=list(r);need(r.fieldnames==['group','slot','slack_ns','data_ns','levels','from','to'],'wrong path schema')
        by={};want={(source+'-'+bus,i) for source in ('all','miss') for bus in ('qm','qk') for i in range(40) if (source,bus,i)!=('miss','qm',39)}
        for row in rows:
            g=row['group'];i=int(row['slot']);src,reg=g.split('-');a=row['from'];z=row['to'];s,t=float(row['slack_ns']),float(row['data_ns']);lv=int(row['levels'])
            need((g,i) in want and (g,i) not in by and z==f'{reg}_reg[{i}]/D' and re.fullmatch(r'q_\w+_reg(?:\[\d+\])?/C',a) and (src!='miss' or a=='q_miss_reg/C'),'unexpected, duplicated or cross-wired path')
            need(math.isfinite(s) and math.isfinite(t) and t>=0 and lv>=0,'invalid timing');by[g,i]=dict(slot=i,slack_ns=s,data_ns=t,levels=lv,start=a,end=z)
        need(by.keys()==want,'missing path');endpoints[name]=by
        need(min(v['slack_ns'] for (g,_),v in by.items() if g.startswith('all-'))==float(sta[0]),'unaccounted worst setup path')
        resources=util.split('1.1 Summary of Registers by Type\n---',1)[0]
        result[name]=dict(routed_nets=counts[1],routing_errors=counts[2],wns_ns=float(sta[0]),whs_ns=float(sta[4]),wpws_ns=float(sta[8]),lut=int(single(r'^\| CLB LUTs\s*\|\s*(\d+)\s*\|.*$',resources)),registers=int(single(r'^\| CLB Registers\s*\|\s*(\d+)\s*\|.*$',resources)),slot8={g:by[g,8] for g in ('all-qm','miss-qm','all-qk','miss-qk')},worst_miss_to_move=min((v for (g,i),v in by.items() if g=='miss-qm'),key=lambda p:p['slack_ns']),report_sha256={n:digest(d/n) for n in ('route.rpt','timing.rpt','util.rpt','paths.tsv')})
    gain=[round(endpoints['candidate']['miss-qm',i]['slack_ns']-endpoints['stock']['miss-qm',i]['slack_ns'],3) for i in range(39)]
    return dict(scope='Registered extracted integer-issue move and keep cones only, one placement and route per variant; no LSU, payload, p2 capture or SoC congestion. Not board timing or CoreMark.',period_ns=5.714,part='xcvu9p-flga2104-2L-e',cone_sha256=hashes,cases=result,miss_to_move_improved=sum(d>0 for d in gain),miss_to_move_unchanged=gain.count(0),miss_to_move_worsened=sum(d<0 for d in gain),miss_to_move_slack_gain_ns_by_slot=gain)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('proof','pair','console'):p.add_argument(name,type=Path)
    a=p.parse_args();print(json.dumps(collect(a.proof,a.pair,a.console),indent=2))
