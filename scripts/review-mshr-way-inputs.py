#!/usr/bin/env python3
"""Cross-check the eleven S1 arrival reports against the path objects of one private post-opt DCP."""
import argparse
import csv
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import os
import shlex

CLOCK = 'clk_out1_harnessSysPLL'
BASE = 'chiptop0/system/tile_prci_domain/element_reset_domain_boom_tile/dcache/'
SINKS = {'s2_tag_match_way_0_reg': 8, 's2_replaced_way_en_REG_reg': 3}
HEADER = 'sink bit from to levels data_ns slack_ns requirement_ns'.split()


def digest(path):
    h = sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def measure(text, row):
    def one(pattern):
        found = re.findall(pattern, text, re.MULTILINE)
        if len(found) != 1:
            raise ValueError('missing or repeated field: ' + pattern)
        return found[0]

    one(r'^\| Tool Version\s*:\s*Vivado v\.2024\.2\b[^\n]*$')
    one(r'^\| Design State\s*:\s*Optimized\s*$')
    one(r'^\| Design\s*:\s*VCU118FPGATestHarness\s*$')
    one(r'^\| Device\s*:\s*xcvu9p-flga2104\s*$')
    one(r'^  Path Type:\s+Setup \(Max at Slow Process Corner\)\s*$')
    sink, bit = row['sink'], int(row['bit'])
    src = one(r'^  Source:\s+(\S+)\s*$'); dst = one(r'^  Destination:\s+(\S+)\s*$')
    tag = sink == 's2_tag_match_way_0_reg'
    src_family = 'meta_0/tag_array/tag_array_ext/mem_0_0/ram_RW_0_r_addr_pipe_0_reg[1]/C' if tag else f'lfsr_prng/state_{bit}_reg/C'
    if (src != BASE + src_family or src != row['from'] or dst != row['to']
            or dst != f'{BASE}{sink}[{bit}]/D' or bit not in range(SINKS[sink])):
        raise ValueError('wrong path endpoints')
    group = one(r'^  Path Group:\s+(\S+)\s*$')
    req = one(r'^  Requirement:\s+([.\d]+)ns\s+\(')
    periods = re.findall(r'^\s*\(rising edge-triggered cell FD[RS]E clocked by (\S+)\s+\{[^}\n]*period=([.\d]+)ns\}\)\s*$', text, re.M)
    if group != CLOCK or req != '5.714' or periods != [(CLOCK, req)] * 2:
        raise ValueError('wrong clocks, edges or period')
    status, slack = one(r'^Slack \((MET|VIOLATED)\)\s*:\s+(-?[\d.]+)ns\s')
    levels = one(r'^  Logic Levels:\s*(\d+)\b'); data, logic, route = one(r'^  Data Path Delay:\s+([\d.]+)ns\s+\(logic ([\d.]+)ns \([^)]*\)\s+route ([\d.]+)ns ')
    if ((levels, data, slack, req) != tuple(row[k] for k in HEADER[-4:])
            or abs(Decimal(data)-Decimal(logic)-Decimal(route)) > Decimal('0.001')
            or (Decimal(slack) >= 0) != (status == 'MET') or 'unplaced)' not in text):
        raise ValueError('inconsistent path metrics or placement state')
    return {'levels': int(levels), 'estimated_data_ns': data, 'estimated_slack_ns': slack}


def review(folder):
    tsv = folder/'paths.tsv'
    with tsv.open(newline='') as f:
        reader = csv.DictReader(f, delimiter='\t'); rows = list(reader)
        if reader.fieldnames != HEADER:
            raise ValueError('unexpected path table')
    expect = {(s, str(b)) for s,w in SINKS.items() for b in range(w)}
    got = [(r['sink'],r['bit']) for r in rows]
    if len(got) != len(expect) or set(got) != expect:
        raise ValueError('duplicate/missing endpoint')
    if {p.name for p in folder.glob('*.rpt')} != {f'{s}-{b}.rpt' for s,b in expect}:
        raise ValueError('unexpected/missing report')
    evidence = {}; by_sink = {s: [] for s in SINKS}
    for row in rows:
        p = folder / '{sink}-{bit}.rpt'.format(**row); m = measure(p.read_text(),row)
        evidence[p.name] = digest(p); by_sink[row['sink']].append(m)
    groups = {}
    for s, ms in by_sink.items():
        groups[s] = {'endpoints': len(ms), 'levels_range': [min(m['levels'] for m in ms), max(m['levels'] for m in ms)],
                     'max_data_ns': str(max(Decimal(m['estimated_data_ns']) for m in ms)),
                     'min_slack_ns': str(min(Decimal(m['estimated_slack_ns']) for m in ms))}
    return {'scope': 'Worst same-clock setup arrival to each selected register D on original three-wide post-opt design only. Unplaced estimates, not the retimed candidate, overall WNS, routing, Fmax or a score.',
            'requested_period_ns': '5.714', 'groups': groups, 'inputs_sha256': {'paths.tsv': digest(tsv), **evidence}}


def attach_run(result, reports, checkpoint, logfile):
    text = logfile.read_text()
    def unique(pattern):
        (v,) = re.findall(pattern, text, re.M); return v
    unique(r'^MSHR_WAY_BASELINE_S1_CHECKPOINT_QUERY_COMPLETE$')
    unique(r'^INFO: \[Common 17-206\] Exiting Vivado at .+$')
    if re.search(r'^ERROR:', text, re.M): raise ValueError('failed Vivado run')
    def local(p):
        p = p.strip('"').replace(chr(92), '/')
        if os.name != 'nt' and re.match(r'^[a-zA-Z]:/',p): p = '/mnt/'+p[0].lower()+'/'+p[3:]
        return Path(p)
    cwd = local(unique(r'^# Current directory\s*:\s*(.+)$'))
    command = shlex.split(unique(r'^# Command line\s*:\s*(.+)$'),posix=False)
    def path(k): return (cwd/local(k)).resolve(strict=True)
    dcp, folder = map(path, command[command.index('-tclargs')+1:])
    source = path(command[command.index('-source')+1]); reference = Path(__file__).with_name('measure-mshr-way-inputs.tcl')
    if dcp != checkpoint.resolve(strict=True) or folder != reports.resolve(strict=True) or source.read_text() != reference.read_text():
        raise ValueError('mismatched checkpoint, report directory or Tcl')
    return dict(result, checkpoint_sha256=digest(dcp), vivado_log_sha256=digest(logfile))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path); parser.add_argument('checkpoint', type=Path)
    parser.add_argument('vivado_log', type=Path); args = parser.parse_args()
    result = attach_run(review(args.reports), args.reports, args.checkpoint, args.vivado_log)
    print(json.dumps(result, indent=2))
