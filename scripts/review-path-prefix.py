#!/usr/bin/env python3
"""Separate arrival *before* the first issue-unit input from the remaining estimate.
Uses Vivado's cumulative times, not net fanout or rounded per-element increments.
No placement, routing, path exceptions, frequency or board actions.
"""
import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

CLK='clk_out1_harnessSysPLL'
BASE='chiptop0/system/tile_prci_domain/element_reset_domain_boom_tile/'
START=BASE+'dcache/s2_tag_match_way_0_reg[0]/C'


def segment(text):
    if not re.search(r'^\| Design State\s*:\s*Optimized\s*$',text,re.M):raise ValueError('wrong implementation stage')
    if len(re.findall(r'^Slack\b',text,re.M))!=8:raise ValueError('missing or extra detailed path')
    sections=re.split(r'^Slack \(VIOLATED\)\s*:\s*',text,flags=re.M)[1:]
    if len(sections)!=8:raise ValueError('expected all eight detailed setup paths')
    results=[]; common=None
    for section in sections:
        def one(pat):
            (v,)=re.findall(pat,section,re.M);return v
        src=one(r'^  Source:\s+(\S+)\s*$');dst=one(r'^  Destination:\s+(\S+)\s*$')
        requirement=Decimal(one(r'^  Requirement:\s*([0-9.]+)ns\s+\(')); budget=Decimal(one(r'^  Data Path Delay:\s*([\d.]+)ns\s+\('));levels=int(one(r'^  Logic Levels:\s*(\d+)\s+\('))
        scd=Decimal(one(r'^    Source Clock Delay\s+\(SCD\):\s+([\d.]+)ns\s*$'))
        if one(r'^  Path Type:\s+(.+?)\s*$')!='Setup (Max at Slow Process Corner)':raise ValueError('not a max setup path')
        if src!=START or not dst.startswith(BASE+'core/') or one(r'^  Path Group:\s+(\S+)\s*$')!=CLK or requirement!=Decimal('5.714'):raise ValueError('unmatched clock, source or endpoint')
        rows=section.splitlines();edges=[]
        for pin in (src,dst):
            (i,)=[i for i,row in enumerate(rows) if re.fullmatch(r'\s*FDRE\s+[rf]\s+'+re.escape(pin)+r'\s*',row)];edges.append(i)
        beg,end=edges
        if beg>=end:raise ValueError('invalid data path')
        prior=None; arrival=None; ingress=None; count=0;prefix_count=None; arc_trace=[]; pending=None; phase='launch'
        for row in rows[beg+1:end]:
            if re.fullmatch(r'\s*[- ]+\s*',row):continue
            # Both logic arcs and nets print their incremental and accumulated times.
            timed=re.fullmatch(r"\s*(.*?)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(?:[rf]\s+)?(\S+)\s*",row)
            if timed:
                role,delta,t,pin=timed.groups();delta,t=Decimal(delta),Decimal(t)
                if phase=='launch':
                    if not role.startswith('FDRE (Prop_FDRE_C_Q)') or pin!=src[:-1]+'Q':raise ValueError('missing launch clock-to-Q')
                    prior=t-delta
                    if abs(prior-scd)>Decimal('.001'):raise ValueError('source clock delay mismatch')
                elif abs((t-arrival)-delta)>Decimal('.002'):raise ValueError('inconsistent time row')
                arrival=t
                if phase=='launch': phase='net'
                elif phase=='net' and role.startswith('net (fo='): phase='input'
                elif phase=='cell' and role.startswith(('LUT','MUXF','CARRY')):
                    cell,port=pending.rsplit('/',1)
                    if pin!=cell+'/O' or '_'+port+'_O)' not in role:raise ValueError('cell input/output discontinuity')
                    count+=1;phase='net'
                else:raise ValueError('unexpected data path row: '+role)
                arc_trace.append((role,pin))
            else:
                (pin,)=re.findall(r'^\s*[rf]\s+(\S+)\s*$',row)
                if phase!='input':raise ValueError('missing incoming net')
                phase='cell';pending=pin
                if ingress is None and re.match(re.escape(BASE)+r'core/(?:int|mem|fp)_issue_unit/',pin):
                    if arrival is None or not re.search(r'/(I\d+|S|CI)$',pin):raise ValueError('not an issue-unit logic input')
                    ingress=arrival; prefix_count=count
        if phase!='input' or ingress is None or prior is None or abs(arrival-prior-budget)>Decimal('.002') or count!=levels:raise ValueError('incomplete or inconsistent path decomposition')
        # Work out the shared run of actual mapped logic output pins; net names can
        # reflect cross-hierarchy synthesis and are not inferred Chisel stages.
        pins=[pin for role,pin in arc_trace if not role.startswith('net')]
        if common is None:common=pins
        else:
            j=next((j for j,(x,y) in enumerate(zip(common,pins)) if x!=y),min(len(common),len(pins)));common=common[:j]
        suffix=dst[len(BASE):]; role='dispatch_credit' if re.fullmatch(r'core/int_issue_unit/io_dis_uops_\d_ready_REG_reg/D',suffix) else ('slot_operand' if re.fullmatch(r'core/(?:int|mem)_issue_unit/slots_\d+/p[12]_reg/D',suffix) else None)
        if role is None:raise ValueError('unrecognized endpoint')
        results.append(dict(endpoint=suffix,kind=role,levels=levels,levels_before_first_issue_input=prefix_count,before_first_issue_input_ns=str(ingress-prior),from_first_issue_input_to_capture_ns=str(arrival-ingress),reported_data_ns=str(budget)))
    if len(set(r['endpoint'] for r in results))!=8 or len(common or [])<2 or not common[-1].startswith(BASE):raise ValueError('duplicate endpoints or no shared logic')
    return dict(scope='Top eight detailed setup paths from the optimized, unplaced three-wide 175 MHz checkpoint. Boundaries use first named mapped issue-unit primitive input, not a portable RTL cut, routed delay or four-wide timing.',requested_period_ns='5.714',shared_combinational_cells_after_launch=len(common)-1,last_shared_output=common[-1][len(BASE):],paths=results)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('max_timing_report',type=Path);a=p.parse_args();b=a.max_timing_report.read_bytes();r=segment(b.decode());r['report_sha256']=sha256(b).hexdigest();print(json.dumps(r,indent=2))
