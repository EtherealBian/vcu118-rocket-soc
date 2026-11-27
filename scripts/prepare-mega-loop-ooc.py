#!/usr/bin/env python3
"""Prepare two identically registered OOC cases from the proved, sealed loop RTL."""
import argparse
import json
from pathlib import Path
import re
import runpy
from hashlib import sha256

D=runpy.run_path(str(Path(__file__).with_name('derive-mega-loop-repair.py')))


def wrapper(src):
    pins=re.findall(r'^  (input|output)\s+(?:\[(\d+):0\]\s+)?(\w+),?\s*$',re.sub(r'//[^\n]*','',src),re.M)
    if len(pins)!=134 or [n for d,w,n in pins if n=='clock']!=['clock']:
        raise ValueError('unexpected interface')
    ports=[]; nets=[]; regs=[]; connections=[]
    for direction,last,name in pins:
        bus=f'[{last}:0] ' if last else ''
        ports.append(f'{direction} {bus}{name}')
        if name=='clock':
            connections.append('.clock(clock)');continue
        # Keep the launch/capture boundaries even on purely passing signals.
        # Do not preserve anything inside the predictor itself.
        q='b_'+name
        nets.append(f'(* DONT_TOUCH="yes" *) reg {bus}{q};')
        if direction=='output':
            nets.append(f'wire {bus}v_{name}; assign {name}={q};'); regs.append(f'{q} <= v_{name};'); connections.append(f'.{name}(v_{name})')
        else:
            regs.append(f'{q} <= {name};');connections.append(f'.{name}({q})')
    return 'module loop_boundary('+',\n'.join(ports)+');\n'+'\n'.join(nets)+'\n'+D['BANK']+' dut(\n'+',\n'.join(connections)+');\nalways @(posedge clock) begin\n'+'\n'.join(regs)+'\nend\nendmodule\n'


def prepare(kit, report, fresh):
    stock=D['sealed'](kit); cand=D['derive'](stock); result=json.loads(report.read_bytes()); digest=lambda b:sha256(b).hexdigest()
    if (result['kit_sha256']!=D['KIT'] or result['source_sha256']!=D['HASHES'] or result['candidate_sha256']!={k:digest(v.encode()) for k,v in cand.items()} or result['formal']['candidate']['decision']!='equivalent_step' or result['formal']['ignore_bit35']['decision']!='counterexample' or result['lockstep']['ignore_bit35']!='output_mismatch'):
        raise ValueError('qualification result does not identify these case files')
    fresh.mkdir();(fresh/'boundary.v').write_bytes(wrapper(stock[D['BANK']]).encode()); (fresh/'loop.xdc').write_bytes(b'create_clock -name cpu -period 5.714 [get_ports clock]\n')
    for name,src in [('stock',stock),('candidate',cand)]:
        d=fresh/name;d.mkdir()
        for n,text in src.items(): (d/(n+'.sv')).write_bytes(text.encode())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('kit','qualification_json','fresh'):p.add_argument(n,type=Path)
    a=p.parse_args();prepare(a.kit,a.qualification_json,a.fresh)
