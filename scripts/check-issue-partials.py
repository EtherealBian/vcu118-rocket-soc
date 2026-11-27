#!/usr/bin/env python3
"""Fail closed unless all three generated Mega issue queues register 4-slot partial sums."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re


def check(rtl):
    counts=[]; hashes={}
    for p in sorted(rtl.glob('IssueUnitCollapsing*.sv')):
        raw=p.read_bytes();text=re.sub(r'//[^\n]*','',raw.decode());hashes[p.name]=sha256(raw).hexdigest()
        ids=set(map(int,re.findall(r'\b_slots_(\d+)_io_will_be_valid\b',text)))
        if len(ids) not in (24,32,40) or ids!=set(range(len(ids))):raise ValueError('unexpected issue depth')
        pat=r'\breg\s+\[2:0\]\s+(vcuAvailPartials_\d+)\s*;'
        names=re.findall(pat,text)
        if len(names)!=len(ids)//4 or len(set(names))!=len(names):raise ValueError('partial group registers absent: '+p.name)
        if re.search(r'io_dis_uops_\d+_ready_REG\s*<=',text):raise ValueError('old output stage remains')
        lanes=re.findall(r'\bassign\s+io_dis_uops_(\d+)_ready\s*=',text)
        if sorted(lanes)!=['0','1','2','3'] or any(len(re.findall(r'\b'+n+r'\s*<=',text))!=1 for n in names):raise ValueError('missing group drivers or ready outputs')
        counts.append(len(ids))
    if sorted(counts)!=[24,32,40]:raise ValueError('incomplete four-wide issue unit set')
    return dict(issue_slots=counts,registered_group_counts=[v//4 for v in counts],inputs=hashes,
                scope='Generated structure only; kernel correctness and routed timing measured separately.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rtl',type=Path)
    print(json.dumps(check(p.parse_args().rtl),indent=2))
