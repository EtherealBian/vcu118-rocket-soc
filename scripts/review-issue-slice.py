#!/usr/bin/env python3
"""Compare two matched routed issue-count slices. No CPU Fmax or board score."""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TOPS = ('issue_ref', 'issue_partial')
PASS = 'ISSUE_SLICE_CYCLE_CHECK_PASS cycles=210703 checked=210701 positions=40 weights=0..40 lanes=4'


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def check_miter(lines, expected):
    if not lines or lines[-1] != PASS or lines.count(PASS) != 1:
        raise ValueError('incomplete or repeated cycle miter')
    inputs = [line.split() for line in lines if line.startswith('ISSUE_SLICE_INPUT')]
    if len(inputs) != len(expected) or any(len(s) != 3 for s in inputs) or {name: h for _, h, name in inputs} != expected:
        raise ValueError('miter inputs differ from the audited files')


def one(text, pattern):
    hits = re.findall(pattern, text, re.M)
    if len(hits) != 1:
        raise ValueError('expected one field: ' + pattern)
    return hits[0]


def check_header(text, top, utilization=False):
    layout = {'Device': 'xcvu9p-flga2104-2L-e'} if utilization else {'Device': 'xcvu9p-flga2104', 'Temperature Grade': 'E'}
    for key, value in {'Design': top, 'Design State': 'Routed', **layout}.items():
        if one(text, rf'^\| {key}\s+: ([^\n]+?)\s*$') != value:
            raise ValueError('wrong ' + key)
    one(text, r'^\| Speed File\s+: (-2L)\b.*$')
    one(text, r'^\| Tool Version\s+: Vivado v\.(2024\.2)\s+.*$')


def review(work, stock, miter):
    fp = load('review-fpga')
    fixtures = load('issue-ready-fixture').fixtures(stock.read_bytes())
    expected = {top + '.sv': sha256(source.encode()).hexdigest() for top, source in zip(TOPS, fixtures)}
    expected.update({name: digest(ROOT / 'tests' / name) for name in ('issue_ready_miter.v', 'issue_ready_slice.cpp')})
    check_miter(miter.read_text(encoding='utf-8-sig').splitlines(), expected)
    if (work / 'vivado.log').read_text().splitlines().count('ISSUE_SLICE_TWO_OOC_ROUTES_COMPLETE') != 1:
        raise ValueError('incomplete paired OOC routes')
    runs = {}
    for top in TOPS:
        sv, d = work / (top + '.sv'), work / top
        if digest(sv) != expected[sv.name]:
            raise ValueError('wrong fixture HDL')
        reports = {name: (d / (name + '.rpt')).read_text() for name in ('route', 'summary', 'setup', 'util')}
        for key in ('setup', 'summary', 'util'):
            check_header(reports[key], top, utilization=(key == 'util'))
        route, timing = fp.route(reports['route']), fp.timing(reports['summary'])
        coverage = {k: n for k, n in fp.counters(reports['summary']).items() if n}
        if coverage != {'no_input_delay': 40, 'no_output_delay': 4}:
            raise ValueError('unexpected clock, endpoint or port coverage')
        if route['routable'] != route['fully_routed'] or route['routable'] <= 0 or route['routing_errors'] != 0:
            raise ValueError('incomplete route')
        sections = re.split(r'(?m)^Slack \((?:MET|VIOLATED)\)\s*:', reports['setup'])
        if len(sections) < 2:
            raise ValueError('missing worst register path')
        worst = sections[1]
        if (float(one(worst, r'^\s*([-\d.]+)ns')) != timing['setup']['slack_ns'] or
                float(one(worst, r'^  Requirement:\s+([\d.]+)ns')) != 5.714 or
                one(worst, r'^  Path Group:\s+(\S+)') != 'clk'):
            raise ValueError('clock or path mismatch')
        logic = one(reports['util'], r'^1\. CLB Logic\n-+\n([\s\S]*?)^1\.1 Summary of Registers by Type$')
        cells = {key: int(one(logic, r'^\|\s*' + key + r'\*?\s*\|\s*(\d+)\s*\|'))
                 for key in ('CLB LUTs', 'CLB Registers')}
        runs[top] = dict(route=route, timing=timing, unconstrained_ports=coverage,
                         worst_setup_logic_levels=int(one(worst, r'^  Logic Levels:\s+(\d+)')),
                         worst_setup_data_ns=float(one(worst, r'^  Data Path Delay:\s+([\d.]+)ns')),
                         start=one(worst, r'^  Source:\s+(\S+)'), end=one(worst, r'^  Destination:\s+(\S+)'),
                         cells=cells, hashes={p.name: digest(p) for p in [sv, *[d / (k + '.rpt') for k in reports]]})
    return dict(scope='40 already-computed slot availability bits to four dispatch credits; registered-port OOC fixture, not whole CPU timing, Fmax or a board benchmark.',
                part='xcvu9p-flga2104-2L-e', period_ns=5.714, rtl_cycle_checks=210701, miter_inputs=expected,
                stock_issue_sha256=digest(stock), runs=runs,
                setup_slack_change_ns=round(runs['issue_partial']['timing']['setup']['slack_ns'] - runs['issue_ref']['timing']['setup']['slack_ns'], 3))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work', 'stock_issue_sv', 'miter_log'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(review(args.work, args.stock_issue_sv, args.miter_log), indent=2))
