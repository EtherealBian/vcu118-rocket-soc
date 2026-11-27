#!/usr/bin/env python3
"""Cross-check VCU118 pulse representatives, clock sources and domain totals; not signoff."""
import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy

from routed_replay import COMMANDS, compare_reports, report_header, section

HERE = Path(__file__).resolve().parent
PULSE, TIMING, CLOCKS = 'pulse-width.rpt', 'full-timing.rpt', 'routed-clocks.rpt'
PULSE_SHA = {'split5h-impl-a': '6ea6d7b6fcb2313538f45b833b366fc85123ed4de803b8ca7039aef841038270',
             'perf-boom5i-impl-a': 'd25eee44bd08e658bbc31fd526b93bbe3ba70f1d5715e264d5de98545a057ca6'}
NUM = r'-?\d+\.\d{3}'
COLUMNS = ('Check Type', 'Corner', 'Lib Pin', 'Reference Pin', 'Required(ns)', 'Actual(ns)', 'Slack(ns)', 'Location', 'Pin')
CPU = 'clk_out1_harnessSysPLL'
DBG = 'dbg_hub/inst/BSCANID.u_xsdbm_id/SWITCH_N_EXT_BSCAN.bscan_inst/SERIES7_BSCAN.bscan_inst/INTERNAL_TCK'
# Known clock/check coverage for this exact board integration; changes need native review.
PLL = {'pll_clk[%d]' % i for i in range(3)}
DOMAINS = {CPU, DBG, 'JTCK', 'sys_clock', 'mmcm_clkout0', 'mmcm_clkout5', 'mmcm_clkout6'} | PLL | {p+'_DIV' for p in PLL}
GRID = Decimal('.001')


def demand(ok, why):
    if not ok:
        raise ValueError(why)


def one(pattern, text):
    hits = re.findall(pattern, text, re.M)
    demand(len(hits) == 1, 'missing or repeated field: '+pattern)
    return hits[0]


def sources(value):
    pins = tuple(value.strip().split())
    demand(pins and len(pins) == len(set(pins)), 'empty or duplicate clock source')
    return pins


def clock_inventory(text):
    head = one(r'^Clock +Period\(ns\) +Waveform\(ns\) +Attributes +Sources *$', text)
    body = text.split(head+'\n', 1)[1].split('\n===', 1)[0].strip()
    out = {}
    for line in body.splitlines():
        name, period, rise, fall, pins = one(r'^(\S+) +('+NUM+r') +\{('+NUM+r') ('+NUM+r')\} +[A-Z,]+ +\{([^{}]+)\} *$', line)
        demand(name not in out, 'duplicate routed clock')
        out[name] = (period, rise, fall, sources(pins))
    demand(out.keys() == DOMAINS, 'unexpected routed clock coverage')
    return out


def parse_block(block):
    lines = block.strip().splitlines()
    demand(len(lines) >= 7 and not lines[4].strip(), 'incomplete pulse block')
    clock = one(r'^Clock Name: +(\S+) *$', lines[0]); demand(clock in DOMAINS, 'unreviewed clock')
    rise, fall = one(r'^Waveform\(ns\): +\{ ('+NUM+r') ('+NUM+r') \} *$', lines[1])
    period = one(r'^Period\(ns\): +('+NUM+r') *$', lines[2]); demand(Decimal(period) > 0, 'nonpositive period')
    pins = sources(one(r'^Sources: +\{ ([^{}]+) \} *$', lines[3]))
    demand(tuple(re.split(r'\s{2,}', lines[5].strip())) == COLUMNS, 'unexpected pulse table header')
    expected = ['Min Period'] + (['Max Period'] if clock in ('sys_clock','mmcm_clkout0') else [])
    expected += ['Low Pulse Width', 'High Pulse Width'] + (['Max Skew'] if clock in PLL | {'mmcm_clkout6'} else [])
    rows = []
    for line in lines[6:]:
        cols = tuple(re.split(r'\s{2,}', line.strip()))
        demand(len(cols) == len(COLUMNS), 'invalid pulse representative columns')
        kind, corner, lib, ref, req, act, slack, loc, pin = cols
        demand(all(re.fullmatch(NUM, n) for n in (req,act,slack)) and
               corner in ('n/a','Slow','Fast') and '/' in lib and loc != 'n/a' and '/' in pin and
               (('/' in ref) if kind == 'Max Skew' else ref == 'n/a'), 'invalid pulse fields')
        difference = Decimal(act)-Decimal(req)
        if kind in ('Max Period','Max Skew'):
            difference = -difference
        # Three separately rounded 1 ps numbers: residual is integral ps and at most 1 ps.
        demand(abs(difference-Decimal(slack)) <= GRID, 'inconsistent '+kind+' slack')
        rows.append(cols)
    demand([r[0] for r in rows] == expected, 'missing, duplicate, reordered or unreviewed check type: '+clock)
    return clock, ((period,rise,fall,pins), tuple(rows))


def blocks(parts):
    result = {}
    for part in parts:
        name, entry = parse_block(part)
        demand(name not in result, 'duplicate pulse clock')
        result[name] = entry
    demand(result.keys() == DOMAINS, 'incomplete pulse clock inventory')
    return result


def standalone(body):
    parts = re.split(r'(?=^Clock Name:)', body.strip(), flags=re.M)
    demand(parts.pop(0).strip() == 'Pulse Width Report', 'unexpected standalone pulse report')
    return blocks(parts)


def embedded(timing, per_clock):
    pattern = r'^Pulse Width Checks\n-{20,} *\n(.*?)\n(?=-{20,} *\n|\Z)'
    found = re.findall(pattern, timing, re.S | re.M)
    demand(len(found) == len(re.findall('^Pulse Width Checks$', timing, re.M)), 'malformed embedded pulse section')
    result = blocks(found)
    for group in re.split(r'(?=^From Clock:)', timing, flags=re.M):
        if '\nPulse Width Checks\n' not in group: continue
        name = one(r'^Clock Name: +(\S+) *$', group)
        src, dst = one(r'^From Clock: +(\S+) *\n +To Clock: +(\S+) *$', group)
        count, w, t = one(r'^PW +: +(\d+) +Failing Endpoints, +Worst Slack +('+NUM+
                          r')ns, +Total Violation +('+NUM+r')ns *$', group)
        demand(src == dst == name and name in per_clock and
               (Decimal(w),Decimal(t),int(count)) == per_clock[name][:3], 'embedded clock group/summary mismatch')
    return result


def pulse_tuple(fields):
    demand(len(fields) == 4 and all(re.fullmatch(NUM, n) for n in fields[:2]) and
           all(re.fullmatch(r'\d+', n) for n in fields[2:]), 'invalid pulse summary tuple')
    w,t = map(Decimal, fields[:2]); bad,n = map(int,fields[2:])
    # A sub-ps violation can display as -0.000. Preserve its failing endpoint count.
    demand(n > 0 and 0 <= bad <= n and t <= 0 and
           ((w <= 0 and t <= w + GRID) if bad else (w >= 0 and t == 0)), 'contradictory pulse counts or slack')
    return w,t,bad,n


def summary_tuples(timing):
    result = {}
    for title, end in [('Design Timing Summary','Clock Summary'), ('Intra Clock Table','Inter Clock Table')]:
        text = section(timing,title,end)
        head = one(r'^ *(?:Clock +)?WNS\(ns\) +TNS\(ns\).*? +WPWS\(ns\) +TPWS\(ns\) +TPWS Failing Endpoints +TPWS Total Endpoints *$',text)
        lines = text.split(head+'\n',1)[1].splitlines()
        demand(re.fullmatch(r'[ -]+', lines[0]) is not None, 'invalid timing separator')
        if title == 'Design Timing Summary':
            demand(len(lines) >= 2 and not any(re.match(r'\s*-?\d', line) for line in lines[2:]), 'missing or repeated global timing values')
            fields = lines[1].split(); demand(len(fields)==12, 'invalid global timing row')
            overall = pulse_tuple(fields[-4:]); continue
        # Use column boundaries: a row with only setup/hold must not be read as pulse.
        cut = head.index('THS Total Endpoints') + len('THS Total Endpoints')
        for line in lines[1:]:
            if not line.strip() or set(line.strip()) == {'-'}: continue
            prefix = line[:cut].split(); demand(len(prefix) in (1,9), 'unreviewed intra-clock row layout')
            name = prefix[0]; demand(name not in result, 'duplicate intra-clock timing row')
            result[name] = pulse_tuple(line[cut:].split())
    return result, overall


def crosscheck(pulse, inventory, per_clock, overall, archived_rounding=False):
    demand(pulse.keys() == per_clock.keys() == inventory.keys(), 'clock inventories disagree')
    report = {}
    for name in sorted(pulse):
        spec, rows = pulse[name]; w,t,bad,n = per_clock[name]
        demand(spec == inventory[name], 'clock period, waveform or source mismatch: '+name)
        worst = min(Decimal(row[6]) for row in rows)
        # Five archived reports have exactly this 1 ps discrepancy on the 0.625 ns PHY
        # clock. Keep both numbers; do not generalize a tolerance around zero or to CPU.
        known = (archived_rounding and name == 'pll_clk[2]' and spec[0] == '0.625' and not bad and
                 (worst,w) == (Decimal('0.144'),Decimal('0.143')))
        demand(worst == w or known, 'pulse representatives disagree with domain WPWS: '+name)
        report[name] = dict(period_ns=spec[0], source_count=len(spec[3]), representative_checks=len(rows),
                            representative_min_ns=str(worst), representative_min_checks=[r[0] for r in rows if Decimal(r[6])==worst], wpws_ns=str(w),
                            tpws_ns=str(t), failing=bad, endpoints=n)
    w,t,bad,n = overall; vals = list(per_clock.values())
    rounding = GRID * (1+sum(v[2]>0 for v in vals)) / 2
    demand(w == min(v[0] for v in vals) and abs(t-sum(v[1] for v in vals)) <= rounding and
           bad == sum(v[2] for v in vals) and n == sum(v[3] for v in vals), 'global/domain pulse summary mismatch')
    return dict(wpws_ns=str(w), tpws_ns=str(t), failing=bad, endpoints=n, clocks=report)


def audit(folder, pulse=None, archived_rounding=False):
    # Compare full identity inside this printing (including build/speed grade and host),
    # but do not disclose host, local paths or physical instance names in results.
    bodies, ids, base = {}, {}, None
    for name in ((TIMING,CLOCKS,PULSE) if pulse is None else (TIMING,CLOCKS)):
        path = folder/name; raw = path.read_bytes(); ids[name] = sha256(raw).hexdigest()
        meta,bodies[name] = report_header(name,raw.decode().replace('\r\n','\n'),path,
                                          COMMANDS.get(name,'report_pulse_width'))
        identity = {k:v for k,v in meta.items() if k not in ('Command','Date')}
        demand(base is None or identity == base, 'report identities disagree'); base = identity
    if pulse is None: pulse = standalone(bodies[PULSE])
    per_clock, overall = summary_tuples(bodies[TIMING])
    demand(embedded(bodies[TIMING],per_clock) == pulse, 'embedded pulse details differ; inspect native pins, including ties')
    result = crosscheck(pulse,clock_inventory(bodies[CLOCKS]),per_clock,overall,archived_rounding)
    return result, ids, pulse


def historical(artifacts):
    controls = json.loads((HERE.parent/'docs/perf-mega175-clock-scope.json').read_bytes())['historical_controls']
    digest = runpy.run_path(str(HERE/'review-mega-routed-paths.py'))['synth'].digest
    out, samples = {}, []
    for run, expected in PULSE_SHA.items():
        obj = artifacts/run/'obj'; anchor = controls[run]['sha256']
        result, ids, sample = audit(obj/'report', archived_rounding=(run == 'split5h-impl-a'))
        dcp = digest(obj/'post_route.dcp')
        demand(dcp == anchor['post_route.dcp'] and ids[PULSE] == expected and
               all(ids[n] == anchor['report/'+n] for n in (TIMING,CLOCKS)), 'different historical control')
        samples.append(sample)
        out[run] = dict(post_route_sha256=dcp, reports_sha256=ids, **result)
    a,b = samples
    pairs = [(left,right) for key in a for left,right in zip(a[key][1],b[key][1])]
    diff = {label:sum(x[i] != y[i] for x,y in pairs) for i,label in enumerate(COLUMNS)}
    return dict(scope='Historical controls only; no four-wide routed or hardware result.',controls=out,
                control_comparison=dict(representatives=len(pairs), different_rows=sum(x!=y for x,y in pairs),
                                        different_rows_by_field=diff))


def routed(run,kit,log,extra):
    anchor = runpy.run_path(str(HERE/'review-mega-routed-paths.py'))['mega'](run,kit,log)
    original, reopened = run/'obj'/'report', extra/'routed'/'replay'
    replay = json.loads((extra/'replay.json').read_bytes()); checks = compare_reports(original,reopened)
    demand(replay['post_route_dcp_sha256'] == anchor['post_route_dcp_sha256'] and
           replay['reports'] == checks and all(v['matches'] for v in checks.values()), 'DCP/replay mismatch')
    result, ids, pulse = audit(original); other, ids2, _ = audit(reopened,pulse)
    demand(result == other and all(ids[n] == checks[n]['original']['sha256'] and
           ids2[n] == checks[n]['reopened']['sha256'] for n in (TIMING,CLOCKS)), 'changed pulse replay evidence')
    return dict(scope='Standalone pulse details vs original and reopened embedded timing checks. Not signoff.',
                board_input_seal=anchor['board_input_seal'], post_route_sha256=anchor['post_route_dcp_sha256'],
                original_sha256=ids, reopened_sha256=ids2, **result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='mode',required=True)
    sub.add_parser('controls').add_argument('artifacts',type=Path)
    r = sub.add_parser('routed')
    for key in ('run','kit','log','extra'): r.add_argument(key,type=Path)
    a = parser.parse_args()
    print(json.dumps(historical(a.artifacts) if a.mode=='controls' else routed(a.run,a.kit,a.log,a.extra), indent=2))
