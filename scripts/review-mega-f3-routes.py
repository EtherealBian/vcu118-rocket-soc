#!/usr/bin/env python3
"""Reconcile a Vivado registered F3 experiment, not a processor or board timing run."""
import argparse
import contextlib
import csv
import io
import json
import math
import re
import runpy
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
support = runpy.run_path(str(HERE / 'review-mega-loop-ooc.py'))
need, single, digest = (support[k] for k in ('need', 'single', 'digest'))
verify = runpy.run_path(str(HERE / 'test-mega-f3-registered.py'))['check_prepared']
CASES = ('stock', 'prefix_and_compare', 'eligible_lanes')
FIELDS = 'group type capture_bit functional_dependence_required status launch_bit slack_ns data_ns logic_levels'.split()
SCOPE = 'Independent OOC registered F3 cut; no CPU/cache/board timing or CoreMark.'
PART = 'xcvu9p-flga2104-2L-e'
DETAIL = (r'Slack \((?:MET|VIOLATED)\)\s*:\s*(-?[\d.]+)ns[^\n]*\n\s*Source:\s*launch_reg\[(\d+)\]/[CQ]'
          r'.*?Destination:\s*capture_reg\[(\d+)\]/D.*?Data Path Delay:\s*([\d.]+)ns')


def load_proof(inp):
    with contextlib.redirect_stdout(io.StringIO()):
        verify(inp)
    return json.loads((inp / 'result.json').read_bytes())


def dcp_header(path):
    with ZipFile(path) as z:
        need(z.testzip() is None, 'corrupt checkpoint')
        head = ET.fromstring(z.read('dcp.xml'))
        for k, v in [('Top', 'f3_boundary'), ('Part', PART), ('OutOfContext', '1'), ('BUILD_NUMBER', '5239630')]:
            need(head.find(k) is not None and head.find(k).get('Name') == v, 'wrong ' + k + ' in DCP')
        # Omit file/line provenance only; other set_property commands may affect timing.
        lines = [s.strip() for s in z.read('f3_boundary.xdc').decode().splitlines() if s.strip()]
        actual = [s for s in lines if not re.fullmatch(r'set_property (?:SRC_FILE_INFO|src_info) \{[^{}]+\} \[current_design\]', s)]
        need(actual == ['create_clock -period 5.714 -name cpu [get_ports clock]'], 'different checkpoint constraints')
    return digest(path)


def report_header(text, state, device):
    for k, v in [('Design', 'f3_boundary'), ('Design State', state), ('Device', device)]:
        need(single(r'^\| ' + k + r'\s*:\s*(\S+)\s*$', text) == v, 'wrong native report ' + k)
    need('Vivado v.2024.2' in text and 'Build 5239630' in text, 'wrong report tool')


def timing(path, state):
    t = path.read_text()
    report_header(t, state, 'xcvu9p-flga2104')
    need(re.search(r'^cpu\s+\{0\.000 2\.857\}\s+5\.714\s+', t, re.M), 'wrong clock')
    # Both summary and detail repeat these headings. No package I/O is modeled.
    for name, n in [('no_clock', 0), ('unconstrained_internal_endpoints', 0), ('no_input_delay', 556), ('no_output_delay', 82), ('loops', 0)]:
        need(re.findall(r'^\d+\. checking ' + name + r' \((\d+)\)', t, re.M) == [str(n)] * 2, 'unexpected timing coverage: ' + name)
    fields = single(r'^cpu\s+(-?[\d.]+(?:\s+-?[\d.]+){11})\s*$', t).split()
    need(all(math.isfinite(float(x)) for x in fields) and [int(fields[i]) for i in (3, 7, 11)] == [82, 82, 638], 'wrong clock endpoints')
    return dict(wns_ns=float(fields[0]), whs_ns=float(fields[4]), wpws_ns=float(fields[8]), setup_failing=int(fields[2]), hold_failing=int(fields[6]))


def produced(log, dcp):
    paths = re.findall(r"^INFO: \[Common 17-1381\] The checkpoint '([^']+)' has been generated\.$", log, re.M)
    need(sum(Path(p).resolve() == dcp.resolve() for p in paths) == 1, 'missing native DCP identity')


def synthesis(inp, name, d, console):
    need(d.name == name and name in CASES, 'wrong synthesis case')
    log = console.read_text(errors='replace')
    synth = d / 'synthesized.dcp'
    produced(log, synth)
    mods = re.findall(r"^INFO: \[Synth 8-6157\] synthesizing module '([^']+)' \[(.+):1\]$", log, re.M)
    expected = [('f3_boundary', (inp / 'boundary.v').resolve()), ('top', (inp / (name + '.v')).resolve())]
    need([(m, Path(p).resolve()) for m, p in mods] == expected, 'wrong synthesized sources')
    xdc_paths = re.findall(r'^Parsing XDC File \[([^\]]+)\]$', log, re.M)
    need(xdc_paths and {Path(p).resolve() for p in xdc_paths} == {(inp / 'clock.xdc').resolve()}, 'wrong XDC')
    need('synth_design completed successfully' in log, 'incomplete synthesis')
    report = d / 'synthesized-timing.rpt'
    return dict(synthesized_dcp_sha256=dcp_header(synth), synthesized_timing=timing(report, 'Synthesized'), estimated_timing_report_sha256=digest(report))


def endpoints(path, proof):
    by = {}
    req = proof['predicted_lane_to_capture_dependent_bits']
    need(sum(map(len, req)) == 357, 'wrong SAT table')
    with path.open(newline='') as f:
        reader = csv.DictReader(f, delimiter='\t')
        need(reader.fieldnames == FIELDS, 'wrong path table')
        for row in reader:
            need(None not in row and all(v is not None for v in row.values()), 'malformed path row')
            g, t, b = row['group'], row['type'], int(row['capture_bit'])
            key = g, t, b
            valid = (g == 'all' and t in ('max', 'min')) or (g in tuple(map(str, range(8))) and t == 'max')
            need(0 <= b < 82 and key not in by and valid, 'duplicate or invalid path group')
            must = g == 'all' or b in req[int(g)]
            need(row['functional_dependence_required'] == str(int(must)), 'incorrect dependence')
            if row['status'] == 'no_path':
                need(not must and [row[k] for k in FIELDS[-4:]] == ['-'] * 4, 'missing required path')
                by[key] = None
                continue
            launch, slack, data, levels = int(row['launch_bit']), float(row['slack_ns']), float(row['data_ns']), int(row['logic_levels'])
            need(row['status'] == 'path' and 0 <= launch < 556 and (g == 'all' or launch == int(g)), 'invalid timing path')
            need(math.isfinite(slack) and math.isfinite(data) and data >= 0 and levels >= 0, 'invalid timing values')
            by[key] = dict(launch=launch, capture=b, slack_ns=slack, data_ns=data, logic_levels=levels)
    need(len(by) == 820, 'not all 820 groups/captures enumerated')
    return by


def worst(it):
    return min((x for x in it if x is not None), key=lambda r: (r['slack_ns'], r['capture'], r['launch']))


def reports(inp, proof, name, src, src_log, d, console, estimate):
    result = synthesis(inp, name, src, src_log)
    log = console.read_text(errors='replace')
    sha = result['synthesized_dcp_sha256']
    need(d.name == name, 'wrong experiment directory')
    state = 'Synthesized' if estimate else 'Routed'
    reopened = src.resolve() != d.resolve()
    markers = ['F3_INPUT_SYNTH_SHA256 ' + name + ' ' + sha] if reopened else []
    markers += (['F3_REGISTERED_SYNTH_ONLY ' + name, 'F3_REGISTERED_SYNTH_FINISHED_NOT_ROUTE'] if estimate else
                ['F3_REGISTERED_CASE_COLLECTED ' + name, 'F3_REGISTERED_SINGLE_CASE_COLLECTED_NOT_SOC ' + name])
    need([s for s in log.splitlines() if s.startswith('F3_')] == markers and not re.search('^ERROR:', log, re.M), 'incomplete or mixed native run')
    if reopened:
        need('Command: open_checkpoint ' + (src / 'synthesized.dcp').resolve().as_posix() in log, 'wrong opened DCP')
    else:
        need(console.resolve() == src_log.resolve(), 'direct measurement requires its original synthesis console')
    if estimate:
        need(not (d / 'registers-routed.dcp').exists() and not (d / 'route.rpt').exists(), 'routed material in synthesis-only run')
    else:
        produced(log, d / 'registers-routed.dcp')
        result['routed_dcp_sha256'] = dcp_header(d / 'registers-routed.dcp')
        route = (d / 'route.rpt').read_text()
        counts = [int(single(r'# of ' + k + r'\.+\s*:\s*(\d+)\s*:', route)) for k in ('routable nets', 'fully routed nets', 'nets with routing errors')]
        need(counts[0] == counts[1] > 0 and counts[2] == 0, 'route incomplete')
        result['routed_nets'] = counts[1]
    result['path_measurement_state'] = state
    result['path_timing'] = sta = timing(d / 'timing.rpt', state)
    if estimate:
        need(sta == result['synthesized_timing'], 'different synthesized timing when measured')
    u = (d / 'util.rpt').read_text()
    report_header(u, state, PART)
    need(int(single(r'^\| CLB Registers\s*\|\s*(\d+)\s*\|.*$', u)) == 638, 'different register count')
    result['clb_luts'] = int(single(r'^\| CLB LUTs\*?\s*\|\s*(\d+)\s*\|.*$', u))
    by = endpoints(d / 'paths.tsv', proof)
    for t, label in [('max', 'wns_ns'), ('min', 'whs_ns')]:
        glob = worst(by['all', t, b] for b in range(82))
        need(glob['slack_ns'] == sta[label], 'path table does not cover worst slack')
        detailed = (d / f'registers-{t}.rpt').read_text()
        report_header(detailed, state, 'xcvu9p-flga2104')
        corner = 'Setup' if t == 'max' else 'Hold'
        need(re.findall(r'^\s*Path Type:\s+(\w+)', detailed, re.M) == [corner] * 10, 'wrong path corner')
        paths = re.findall(DETAIL, detailed, re.S)
        need(len(paths) == 10 and len({x[2] for x in paths}) == 10, 'wrong 10 native path details')
        for slack, launch, b, data in paths:
            rec = by['all', t, int(b)]
            need((rec['slack_ns'], rec['launch'], rec['data_ns']) == (float(slack), int(launch), float(data)), 'native path details disagree')
    result['sta_lane_pairs_with_path'] = sum(by[str(l), 'max', b] is not None for l in range(8) for b in range(82))
    result['required_lane_pairs'] = 357
    result['worst_per_output_bus'] = {bus: {
        'all_inputs': worst(by['all', 'max', b] for b in range(lo, hi + 1)),
        'eight_directions': worst(by[str(l), 'max', b] for b in range(lo, hi + 1) for l in range(8)),
    } for bus, lo, hi in proof['output_lsb_msb']}
    files = ('paths.tsv', 'timing.rpt', 'util.rpt', 'registers-max.rpt', 'registers-min.rpt') + (() if estimate else ('route.rpt',))
    result['native_report_sha256'] = {n: digest(d / n) for n in files}
    result['candidate_rtl_sha256'] = proof['cut_sha256'][name]
    return result, by


def compare(proof, baseline, candidate):
    """Compare only paths with the exact same source/destination, in reported ps."""
    req = proof['predicted_lane_to_capture_dependent_bits']
    keys = [(str(l), 'max', b) for l, bits in enumerate(req) for b in bits]
    def summary(keys):
        changes = [(round(candidate[k]['slack_ns'] * 1000) - round(baseline[k]['slack_ns'] * 1000), int(k[0]), k[2]) for k in keys]
        def boundary(item):
            delta, lane, bit = item
            return dict(delta_ps=delta, lane=lane, capture_bit=bit)
        return dict(improved=sum(d > 0 for d, _, _ in changes), worsened=sum(d < 0 for d, _, _ in changes),
                    equal=sum(d == 0 for d, _, _ in changes), smallest_delta=boundary(min(changes)), largest_delta=boundary(max(changes)))
    return dict(all_required=summary(keys), by_output_bus={bus: summary([k for k in keys if lo <= k[2] <= hi]) for bus, lo, hi in proof['output_lsb_msb']})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('prepared', type=Path)
    p.add_argument('stage', choices=['estimate', 'route'], help='never combine timing results from different implementation stages')
    p.add_argument('--case', nargs=5, action='append', required=True, metavar=('NAME', 'SYNTH_DIR', 'SYNTH_CONSOLE', 'MEASURE_DIR', 'MEASURE_CONSOLE'))
    a = p.parse_args(); proof = load_proof(a.prepared)
    result = dict(scope=SCOPE, qualification_sha256=digest(a.prepared / 'result.json'), stage=a.stage, cases={})
    tables = {}
    for name, *paths in a.case:
        need(name not in tables, 'repeated case')
        result['cases'][name], tables[name] = reports(a.prepared, proof, name, *map(Path, paths), estimate=a.stage == 'estimate')
    if len(tables) > 1:
        need(set(tables) == set(CASES), 'comparison requires all three cases')
        result['same_required_pair_vs_stock'] = {n: compare(proof, tables['stock'], tables[n]) for n in CASES[1:]}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
