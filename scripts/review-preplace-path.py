#!/usr/bin/env python3
"""Extract the pre-placement CPU setup path, never Fmax or routed slack."""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import re

CLOCK = 'clk_out1_harnessSysPLL'


def review(out):
    detail = out / (CLOCK+'-max.rpt'); table = out/'endpoints.tsv'
    text = detail.read_text(); state = re.findall(r'^\| Design State\s*: (\S+)\s*$', text, re.M)
    if state != ['Optimized'] or 'unplaced)' not in text:
        raise ValueError('expected unplaced, post-opt estimates')
    with table.open(newline='') as f:
        rows = [r for r in csv.DictReader(f,delimiter='\t') if (r['destination_clock'],r['kind'])==(CLOCK,'max')]
    if len(rows)!=40 or len({r['to'] for r in rows})!=40 or sorted(float(r['slack_ns']) for r in rows)!=[float(r['slack_ns']) for r in rows]:
        raise ValueError('expected 40 sorted distinct CPU setup endpoints')
    first = re.split(r'(?m)^Slack \((?:VIOLATED|MET)\)\s*:',text)[1]; row=rows[0]
    def field(pattern):
        m=re.search(pattern,first,re.M)
        if not m: raise ValueError('missing path field: '+pattern)
        return m[1]
    delay=re.search(r'^  Data Path Delay:\s+([\d.]+)ns\s+\(logic ([\d.]+)ns \([\d.]+%\)\s+route ([\d.]+)ns', first, re.M)
    slack=float(field(r'^\s*([-\d.]+)ns'));levels=int(field(r'^  Logic Levels:\s+(\d+)'));req=float(field(r'^  Requirement:\s+([\d.]+)ns'))
    if not delay or float(row['slack_ns'])!=slack or int(row['logic_levels'])!=levels or field(r'^  Source:\s+(\S+)')!=row['from'] or field(r'^  Destination:\s+(\S+)')!=row['to'] or abs(req-1000/175)>.001 or field(r'^  Path Group:\s+(\S+)')!=CLOCK:
        raise ValueError('detail/table/clock mismatch')
    return dict(scope='Post-opt unplaced estimates only. Not post-route timing, board clock or Fmax.',requested_clock_mhz=175,
                setup_endpoints_sampled=len(rows),unique_launch_pins=len({r['from'] for r in rows}),
                endpoints_from_worst_launch=sum(r['from']==row['from'] for r in rows),
                worst_setup=dict(start=row['from'],end=row['to'],slack_ns=slack,requirement_ns=req,logic_levels=levels,
                    data_ns=float(delay[1]),logic_ns=float(delay[2]),estimated_route_ns=float(delay[3]),
                    traverses_dcache_mshr_response_queue='/dcache/mshrs/respq/' in first),
                inputs_sha256={p.name:sha256(p.read_bytes()).hexdigest() for p in (detail,table)})


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report_dir',type=Path)
    print(json.dumps(review(p.parse_args().report_dir),indent=2))
