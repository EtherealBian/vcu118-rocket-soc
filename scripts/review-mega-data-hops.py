#!/usr/bin/env python3
"""Identify the slow physical data interconnects, not clock nets, in eight paths per corner.

Usage: python scripts/review-mega-data-hops.py RUN SEALED_KIT IMPLEMENTATION_LOG
Requires the existing four-wide post-route audit anchor. Offline and read-only.
Unsupported Vivado report shapes are rejected, not interpreted as zero delays.
"""
import argparse
from collections import defaultdict
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
ROUTED = runpy.run_path(str(HERE/'review-mega-routed-paths.py'))
SEP = re.compile(r'^  -{5,}[ \t]+-{5,}[ \t]*$', re.M)
NUMBER = r'-?\d+\.\d{3}'
TIMES = rf'(?P<delay>{NUMBER})\s+(?P<time>{NUMBER})'
SITE = r'[A-Za-z][\w.]*_X\d+Y\d+'
ARC = re.compile(rf'(?P<site>{SITE})\s+\w+ \(Prop_[^()\s]+\)\s+{TIMES}\s+[rf]\s+(?P<pin>\S+)')
NET = re.compile(rf'net \(fo=(?P<fanout>\d+), routed\)\s+{TIMES}\s+(?P<net>\S+)')
PIN = re.compile(rf'({SITE})(?:\s+(\w+))?\s+[rf]\s+(\S+)')
LAUNCH = re.compile(rf'({SITE})\s+\w+\s+(?:{NUMBER}\s+{NUMBER}\s+)?[rf]\s+(\S+)')
CROSS = re.compile(r'SLR Crossing\[([012])->([012])\]')


def decompose(section, detail):
    # Only the data table is between the launch-pin and capture-pin separators.
    # Identical-looking clock columns precede and follow it, often crossing SLRs.
    tables = SEP.split(section)
    if len(tables) < 4:
        raise ValueError('missing timing table boundaries')
    launch = LAUNCH.fullmatch(tables[1].strip().splitlines()[-1].strip())
    if not launch or launch[2] != detail['launch']:
        raise ValueError('data path does not start at launch pin')
    lines = [line.strip() for line in tables[2].splitlines() if line.strip()]
    previous = launch[2]; site = launch[1]; index = 0; hops = []
    arrival = start = None; logic = D(0); routing = D(0)

    def next_line():
        nonlocal index
        if index == len(lines):
            raise ValueError('truncated data table')
        line = lines[index]; index += 1
        return line

    def times(m):
        nonlocal arrival, start
        delta, now = map(D, (m['delay'], m['time']))
        if arrival is None:
            start = now-delta
        elif abs(now-arrival-delta) > D('.001'):
            raise ValueError('discontinuous cumulative delay')
        arrival = now
        return delta

    while index < len(lines):
        line = next_line()
        if line.endswith(')') and '(Prop_' in line:
            line += ' '+next_line()   # wrapped primitive row
        arc = ARC.fullmatch(line)
        if not arc or arc['site'] != site or arc['pin'].rsplit('/', 1)[0] != previous.rsplit('/', 1)[0]:
            raise ValueError('wrong primitive, site or cell at data arc')
        driver = arc['pin']; logic += times(arc)
        net = NET.fullmatch(next_line())
        if not net:
            raise ValueError('missing actual routed data net')
        delta = times(net); routing += delta
        if delta < 0:
            raise ValueError('negative routed interconnect delay')
        line = next_line(); crossings = []
        while (cross := CROSS.fullmatch(line)):
            a,b = map(int,cross.groups())
            if a == b or (crossings and crossings[-1][1] != a):
                raise ValueError('invalid SLR sequence on the data hop')
            crossings.append((a,b)); line = next_line()
        sink = PIN.fullmatch(line)
        if not sink:
            raise ValueError('missing sink after routed data hop')
        hops.append(dict(driver=driver,sink=sink[3],driver_site=site,sink_site=sink[1],net=net['net'],
                         fanout=int(net['fanout']),increment_ns=str(delta),slr_crossings=crossings))
        site,previous = sink[1],sink[3]
    if not hops or previous != detail['capture'] or len(hops) != detail['logic_levels']+1:
        raise ValueError('capture pin or combinational arc count does not reconcile')
    budget = D('.0005')*(len(hops)+1)  # each per-row value independently rounded to 1 ps
    if (abs(logic-D(detail['logic_ns'])) > budget or abs(routing-D(detail['routing_ns'])) > budget or
            abs(arrival-start-D(detail['data_ns'])) > D('.002')):
        raise ValueError('routed data totals do not reconcile')
    return hops


def summarize(text, details):
    sections = re.split(r'(?m)(?=^Slack \((?:MET|VIOLATED)\)\s*:)',text)[1:]
    if len(sections) != 8 or len(details) != 8:
        raise ValueError('expected eight ranked path details')
    out = []; shared = defaultdict(list)
    for rank,(section,d) in enumerate(zip(sections,details),1):
        hops = decompose(section,d)
        keys = [(h['driver'],h['sink']) for h in hops]
        if len(set(keys)) != len(hops):
            raise ValueError('repeated physical arc within a data path')
        for key,hop in zip(keys,hops):
            shared[key].append((rank,hop))
        crossed = [h for h in hops if h['slr_crossings']]
        out.append(dict(rank=rank,slack_ns=d['slack_ns'],capture=d['capture'],routed_hops=len(hops),
                        data_ns=d['data_ns'],route_ns=d['routing_ns'],data_crossing_hops=len(crossed),
                        crossing_hop_delay_sum_ns=str(sum((D(h['increment_ns']) for h in crossed),D('0.000'))),
                        largest_hops=sorted(hops,key=lambda h:D(h['increment_ns']),reverse=True)[:3]))
    repeated=[]
    for key,rows in shared.items():
        if len(rows)<2:continue
        ranks,hops=zip(*rows)
        if any((h['driver_site'],h['sink_site'],h['net'],h['fanout'],h['slr_crossings']) !=
               (hops[0]['driver_site'],hops[0]['sink_site'],hops[0]['net'],hops[0]['fanout'],hops[0]['slr_crossings']) for h in hops[1:]):
            raise ValueError('inconsistent physical identity of repeated timing arc')
        vals=[D(h['increment_ns']) for h in hops]
        repeated.append(dict(driver=key[0],sink=key[1],fanout=hops[0]['fanout'],path_ranks=ranks,
                             min_increment_ns=str(min(vals)),max_increment_ns=str(max(vals))))
    # One physical driver->sink pair may appear on several paths. Do not sum its
    # occurrences into a fictitious chip-wide delay or optimization benefit.
    repeated.sort(key=lambda r:(-len(r['path_ranks']),-D(r['max_increment_ns']),r['driver'],r['sink']))
    return dict(paths=out,distinct_data_hops=len(shared),repeated_hop_count=len(repeated),most_repeated=repeated[:8])


def review(run,kit,log):
    anchor=ROUTED['mega'](run,kit,log); cuts={}
    for kind,group in anchor['paths'].items():
        f=run/'obj/routed-endpoints'/f"{ROUTED['CLOCK']}-{kind}.rpt"; raw=f.read_bytes()
        if sha256(raw).hexdigest() != anchor['report_hashes'][f.name]:
            raise ValueError('detailed timing report changed during review')
        cuts[kind]=summarize(raw.decode().replace('\r\n','\n'),group['details'])
    return dict(scope='Eight detailed CPU-clock destination paths per max/min corner. Net increments are for a particular driver and sink, not net-wide slack or removable delay. SLR annotations exclude clock segments. Not all paths, signoff, Fmax or CoreMark.',
                board_input_seal=anchor['board_input_seal'],post_route_dcp_sha256=anchor['post_route_dcp_sha256'],
                report_hashes=anchor['report_hashes'],samples=cuts)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('run','kit','log'):p.add_argument(n,type=Path)
    a=p.parse_args();print(json.dumps(review(a.run,a.kit,a.log),indent=2))
