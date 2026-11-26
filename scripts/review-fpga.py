#!/usr/bin/env python3
"""Extract routed implementation evidence, NOT board qualification or a timing waiver."""
import argparse, hashlib, json, re
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from board_io_inventory import check_io

def route(text):
    def value(key):
        m=re.search(r'^\s*# of '+key+r'\.+\s*:\s*(\d+)\s*:',text,re.M)
        if not m:raise ValueError('missing route metric: '+key)
        return int(m[1])
    return {k:value(n) for k,n in [('routable','routable nets'),('fully_routed','fully routed nets'),('routing_errors','nets with routing errors')]}

def timing(text):
    m=re.search(r'^\s*WNS\(ns\)\s+TNS\(ns\)[^\n]+TPWS Total Endpoints[^\n]*\n[^\n]*\n([^\n]+)',text,re.M)
    if not m or len(m[1].split())!=12:raise ValueError('missing complete routed summary')
    a=m[1].split();return {n:dict(slack_ns=float(a[k]),total_negative_ns=float(a[k+1]),failed=int(a[k+2]),count=int(a[k+3])) for k,n in [(0,'setup'),(4,'hold'),(8,'pulse_width')]}

def counters(text):
    result={}
    for k, v in re.findall(r'^\s*\d+\. checking (\w+) \((\d+)\)',text,re.M):
        if k in result and result[k]!=int(v):raise ValueError('inconsistent check_timing count: '+k)
        result[k]=int(v)
    if not {'no_clock','unconstrained_internal_endpoints','no_input_delay','no_output_delay',
            'generated_clocks','multiple_clock','loops','latch_loops','partial_input_delay','partial_output_delay'}<=set(result):raise ValueError('missing check_timing coverage summary')
    return result

def board_coverage(ct):
    # I/O still needs a per-pin review. No unconstrained internal endpoints,
    # missing clocks, loops, or unknown nonzero checks can pass this gate.
    return all(not n or k in ('no_input_delay','no_output_delay') for k,n in ct.items())

def gates(rt,tm):
    return rt['routable']>0 and rt['routable']==rt['fully_routed'] and rt['routing_errors']==0 and all(v['slack_ns']>=0 and v['failed']==0 and v['count']>0 and v['total_negative_ns']==0 for v in tm.values())

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('run',type=Path);a=ap.parse_args();d=a.run.resolve();r=d/'obj/report';files={}
    def read(name):
        b=(r/name).read_bytes();files[name]=hashlib.sha256(b).hexdigest();return b.decode(errors='replace')
    rt=route(read('route-status.rpt'));tm=timing(read('full-timing.rpt'));ct_text=read('check-timing.rpt');ct=counters(ct_text);io,io_known=check_io(ct_text,ct);resources={}
    util=read('routed-utilization.rpt');
    for k in ['CLB LUTs','CLB Registers','Block RAM Tile','DSPs','URAM']:
        m=re.search(r'^\|\s*'+k+r'\s*\|\s*([\d.]+)\s*\|',util,re.M)
        if m:resources[k]=float(m[1])
    for n in ['cdc.rpt','clock-interaction.rpt','pulse-width.rpt','methodology.rpt','routed-clocks.rpt','routed-drc.rpt']:read(n)
    bit=d/'obj/VCU118FPGATestHarness.bit';routable=gates(rt,tm)
    print(json.dumps(dict(run=d.name,route=rt,timing=tm,check_timing=ct,resources=resources,route_and_constrained_timing_met=routable,
       board_internal_coverage_met=board_coverage(ct),board_io_inventory_known=io_known,io_detail=io,nonzero_coverage_checks={k:v for k,v in ct.items() if v},reports_sha256=files,bit_sha256=(hashlib.sha256(bit.read_bytes()).hexdigest() if bit.is_file() else None),qualification='manual CDC/DRC/clock/IO coverage and physical testing separate'),indent=2))
    return 0 if routable else 1
if __name__=='__main__':raise SystemExit(main())
