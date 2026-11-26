#!/usr/bin/env python3
"""Check the new IRQ against two sampled destination edges of the original public pin."""
import argparse
from pathlib import Path
import re

def compare(old, new):
    summaries = []
    traces = []
    for d in (old,new):
        if not (d/'test.ok').is_file(): raise ValueError('missing independent functional pass')
        rows=re.findall(r'^HALT_MERGE_CASE_PASS half=(\d+) phase=(\d+) dmi_transactions=(\d+) ticks=(\d+)$',(d/'result.txt').read_text(),re.M)
        if [(int(h),int(p),int(n)) for h,p,n,t in rows] != [(h,p,16) for h in (4,5,7) for p in (0,1,3)]: raise ValueError('incomplete scenario coverage')
        v=(d/'events.bin').read_bytes()
        if len(v)!=sum(int(t) for h,p,n,t in rows): raise ValueError('truncated or extra trace data')
        summaries.append(rows);traces.append(v)
    if summaries[0]!=summaries[1]: raise ValueError('DMI timing differs')
    a,b=traces; offset=0;changes=0
    for h,p,n,t in summaries[0]:
        length=int(t); rawchanges=nonzero=0
        for step,(v,w) in enumerate(zip(a[offset:offset+length],b[offset:offset+length])):
            if v>=64 or w>=64 or ((v^w)&60) or (v>>1)&1 != w&1: raise ValueError(f'clock/handshake/registered IRQ mismatch at half={h} phase={p} tick={step}')
            rawchanges+=int((v&1)!=(w&1)); nonzero+=w&1
        if not 0<nonzero<length or not rawchanges: raise ValueError('vacuous comparison')
        offset+=length; changes+=rawchanges
    return offset,changes

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('original',type=Path);ap.add_argument('split',type=Path);args=ap.parse_args()
    ticks,delta=compare(args.original,args.split);print('HALT_MERGE_TWO_EDGE_EQUIVALENCE_PASS events=%d nonzero_delay_observations=%d'%(ticks,delta))
