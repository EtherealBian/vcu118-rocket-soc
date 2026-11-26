#!/usr/bin/env python3
"""Inspect reachable firtool-generated instances, not the number of SV files or DTS CPUs."""
import argparse, json, re
from pathlib import Path

def check(root, nine=False):
    def body(name):
        p=root/(name+'.sv');s=re.sub(r'//[^\n]*|/\*.*?\*/','',p.read_text(),flags=re.S)
        if not re.search(r'\bmodule\s+'+re.escape(name)+r'\s*\(',s):raise ValueError('missing module '+name)
        return s
    def children(s,base,count):
        found=re.findall(r'^\s*('+base+r'(?:_\d+)?)\s+(\w+)\s*\(',s,re.M)
        if len(found)!=count or len({i for _,i in found})!=count:raise ValueError(f'{base}: need {count} instances, got {found}')
        return found
    top,system=children(body('ChipTop'),'DigitalTop',1)[0];domains=children(body(top),'TilePRCIDomain',4);paths=[]
    for mod,domain in domains:
        t,tile=children(body(mod),'RocketTile',1)[0];tile_body=body(t)
        c,core=children(tile_body,'Rocket',1)[0];core_body=body(c);front,fi=children(tile_body,'Frontend',1)[0]
        if nine:
            for reg in ('alignValid','decodeValid','ex_reg_valid','mem_reg_valid','wb_reg_valid'):
                if not re.search(r'\breg\s+'+reg+r'\s*;',core_body) or not re.search(r'\b'+reg+r'\s*<=',core_body):raise ValueError('missing registered boundary '+reg)
            fq,_=children(body(front),'ShiftQueue',1)[0];q=body(fq)
            if not re.search(r'assign\s+io_deq_valid\s*=\s*valid_0\s*;',q):raise ValueError('fetch queue output not from head valid register; inspect '+fq)
        paths.append('.'.join(('ChipTop',system,domain,tile,core)))
    return {'scope':'generated hierarchy only; not a dynamic latency trace or physical signoff','cores':paths,'nine_structure_checked':nine}
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('rtl',type=Path);ap.add_argument('--nine',action='store_true');a=ap.parse_args();print(json.dumps(check(a.rtl,a.nine),indent=2));print('QUAD_GENERATED_CORE_INSTANCES_PASS')
