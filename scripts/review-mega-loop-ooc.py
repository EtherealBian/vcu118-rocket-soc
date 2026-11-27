#!/usr/bin/env python3
"""Extract a sanitized registered-boundary A/B result from one completed Vivado pair."""
import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path


def need(condition, message):
    if not condition:
        raise ValueError(message)


def single(regex, text):
    rows = re.findall(regex, text, re.M)
    need(len(rows) == 1, 'missing or ambiguous report field: ' + regex)
    return rows[0]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(inputs, outputs, console, proof):
    # Console is the driver's saved stdout, not Vivado's TCL command echo.
    log = console.read_text(errors='replace')
    markers = [s for s in log.splitlines() if s.startswith('LOOP_BANK_OOC_')]
    need(markers == ['LOOP_BANK_OOC_CASE_COMPLETE stock', 'LOOP_BANK_OOC_CASE_COMPLETE candidate',
                     'LOOP_BANK_OOC_PAIR_COMPLETE_NOT_SOC_TIMING'] and not re.search(r'^ERROR:', log, re.M), 'incomplete pair')
    q = json.loads(proof.read_bytes())
    need(q['formal']['candidate']['decision'] == 'equivalent_step' and q['lockstep']['ignore_bit35'] == 'output_mismatch', 'wrong qualification')
    h = {n:digest(inputs/n) for n in ('boundary.v','loop.xdc')}
    need(h == {'boundary.v':'341ffeef7304416e6e163bbc5b4d1cf03e1e9bf7ebcf81f176251a3fa3c2c2f9', 'loop.xdc':'2ce6e590fd43bf60a45d85cb844464dd35e3ad3ea2efd42dc83ca207647af15d'}, 'different boundary or clock')
    pair = {}
    for case, version in [('stock','source_sha256'),('candidate','candidate_sha256')]:
        rtl = {n:digest(inputs/case/(n+'.sv')) for n in ('LoopBranchPredictorBank','LoopBranchPredictorColumn')}
        need(rtl == q[version], 'different RTL')
        d = outputs/case
        route, timing, util = [(d/n).read_text() for n in ('route.rpt','timing.rpt','util.rpt')]
        for text in (timing,util):
            for key, value in [('Design','loop_boundary'),('Design State','Routed')]:
                need(single(r'^\| '+key+r'\s*:\s*(\S+)\s*$', text) == value, 'not a routed loop bank')
        need(single(r'^\| Device\s*:\s*(\S+)\s*$', util) == 'xcvu9p-flga2104-2L-e', 'wrong part')
        need('Vivado v.2024.2' in timing and 'xcvu9p-flga2104' in timing and '-2L  PRODUCTION' in timing and re.search(r'^cpu\s+\{0\.000 2\.857\}\s+5\.714\s', timing, re.M), 'wrong timing context')
        counts = [int(single(r'# of '+k+r'\.+\s*:\s*(\d+)\s*:', route)) for k in ('routable nets','fully routed nets','nets with routing errors')]
        need(counts[0] == counts[1] > 0 and counts[2] == 0, 'incomplete route')
        sta = single(r'^cpu\s+(-?[\d.]+(?:\s+-?[\d.]+){11})\s*$', timing).split()
        with (d/'paths.tsv').open(newline='') as f:
            r = csv.DictReader(f, delimiter='\t'); rows = list(r)
            need(r.fieldnames == ['group','slack_ns','data_ns','levels','from','to'], 'wrong path schema')
        g = [r['group'] for r in rows]
        need(g == ['all-max']*10 + ['all-min']*10 + ['taken-'+str(i) for i in range(4)] + (['early-enable']*4 if case=='candidate' else []), 'missing path groups')
        def path(r):
            for side in ('from','to'):
                need(re.fullmatch(r'[\w./\[\]-]+',r[side]) and not r[side].startswith(('/', '.')), 'non-relative logic path')
            s,t = float(r['slack_ns']),float(r['data_ns']); need(math.isfinite(s) and math.isfinite(t) and t>=0, 'invalid timing')
            return dict(start=r['from'], end=r['to'], slack_ns=s, data_ns=t, logic_levels=int(r['levels']))
        paths = [path(r) for r in rows]
        for i in range(4):
            need(paths[20+i]['end']==f'b_io_resp_f3_{i}_taken_reg/D','wrong capture pin')
        early = paths[24:]; need(len({p['end'] for p in early})==len(early) and all('vcu_f3_repair_bypass_reg' in p['end'] for p in early),'wrong retimed enables')
        need((paths[0]['slack_ns'],paths[10]['slack_ns']) == (float(sta[0]), float(sta[4])), 'global worst paths mismatch')
        use = {n:int(re.search(r'^\| '+n+r'\s*\|\s*(\d+)\s*\|',util,re.M)[1]) for n in ['CLB LUTs','CLB Registers','Block RAM Tile','DSPs']}
        reports = {n:digest(d/n) for n in ['route.rpt','timing.rpt','util.rpt','paths.tsv','registers-max.rpt','registers-min.rpt']+[f'taken-{i}.rpt' for i in range(4)]}
        pair[case] = dict(rtl_sha256=rtl,fully_routed=counts[1],routing_errors=counts[2],wns_ns=float(sta[0]),whs_ns=float(sta[4]),wpws_ns=float(sta[8]),utilization=use,worst_setup=paths[0],taken=paths[20:24],early_enable=early,report_sha256=reports)
    return dict(scope='Vivado 2024.2 registered four-column bank only, xcvu9p-flga2104-2L-e; single implementation per variant. Not full-SoC STA or board performance.',period_ns=5.714,boundary_sha256=h,cases=pair)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('inputs','outputs','console','proof'): p.add_argument(n,type=Path)
    a=p.parse_args(); print(json.dumps(collect(a.inputs,a.outputs,a.console,a.proof), indent=2))
