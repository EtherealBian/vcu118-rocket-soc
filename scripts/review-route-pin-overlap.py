#!/usr/bin/env python3
"""Join exact initial router pin names to the *same run's* ranked CPU capture pins.

Reads files only. An omitted pin has unknown final slack, not passing slack.
The initial report names *launch* clocks; the final sample selects a *capture* clock.
"""
import argparse
import csv
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
DOC = HERE.parent / 'docs'
ROUTED = runpy.run_path(str(HERE / 'review-mega-routed-paths.py'))
CPU = ROUTED['CLOCK']
digest = ROUTED['synth'].digest
LEGACY = {
    'log': 'ec465c5ab4d4e0948078304199b9565b5496fa58a022dbbc603b26f83ca98492',
    'pins': '8f71c7d845ab96e57d647561f90768a01c9b39fea2f7916a7f4407e5ae251d75',
    'endpoints': '6c25eb23ca3f178a974e530f6e3d16f8058c9e7cf1be3d70d14e224eb73c3b54',
    'dcp': '4a7f8856ec1ba968f7751e07148eb8a1cd10498bd4f39f381f2a31bc60fa17f1',
}


def hashed(data):
    return sha256(data).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def pin_rows(text):
    rows = [tuple(v.strip() for v in line[1:-1].split('|'))
            for line in text.splitlines() if line.startswith('|') and line.endswith('|')]
    require(rows and rows[0] == ('Launch Setup Clock', 'Launch Hold Clock', 'Pin'), 'wrong initial table header')
    result = []
    for setup, hold, pin in rows[1:]:
        require(setup == hold == CPU and '/' in pin and not re.search(r'\s', pin), 'unrecognized initial pin or launch clocks')
        result.append(pin)
    require(len(result) == len(set(result)), 'duplicate initial pin')
    return result


def initial(log, table):
    blocks = re.findall(r'^INFO: \[Route 35-580\] Design has (\d+) pins with tight setup and hold constraints\.\n\nThe top 5 pins with tight setup and hold constraints:\n(.*?)^File with complete list of pins: tight_setup_hold_pins\.txt$', log, re.M | re.S)
    require(len(blocks) == 1, 'missing or ambiguous initial routing evidence')
    count, preview = blocks[0]
    pins = pin_rows(table)
    require(len(pins) == int(count) >= 5 and pin_rows(preview) == pins[:5], 'initial pin count or preview mismatch')
    return pins


def join(pins, data):
    positions = {p: i for i, p in enumerate(pins, 1)}
    reader = csv.DictReader(io.StringIO(data.decode('ascii')), delimiter='\t')
    require(reader.fieldnames == ['destination_clock','kind','slack_ns','logic_levels','from','to'], 'wrong endpoint header')
    rows = [r for r in reader if r['destination_clock'] == CPU]
    require(len(rows) == 80, 'expected both 40-endpoint CPU samples')
    samples = {}
    for kind in ('max', 'min'):
        paths = [r for r in rows if r['kind'] == kind]
        require(len(paths) == len({r['to'] for r in paths}) == 40, 'missing or duplicate CPU endpoints')
        require(all(re.fullmatch(r'-?\d+\.\d{3}', r['slack_ns']) and r['to'] and r['from'] for r in paths), 'incomplete path or nonnumeric slack')
        slack = [Decimal(r['slack_ns']) for r in paths]
        require(slack == sorted(slack), 'out-of-order slack')
        hits = [dict(routed_rank=i, initial_list_row=positions[r['to']], slack_ns=r['slack_ns'], launch=r['from'], capture=r['to']) for i,r in enumerate(paths,1) if r['to'] in positions]
        samples[kind] = dict(sample_size=len(paths), worst_slack_ns=paths[0]['slack_ns'], negative_in_sample=sum(s<0 for s in slack), exact_matches=len(hits), from_initial_preview=sum(h['initial_list_row']<=5 for h in hits), matches=hits)
    return samples


def legacy_details(table, data):
    # Archived recovery used -nets and did not run post-route phys_opt. Never
    # relabel its report state to make it pass the four-wide checkout's audit.
    rows = list(csv.DictReader(io.StringIO(data.decode('ascii')), delimiter='\t'))
    ids = {}
    for kind in ('max', 'min'):
        path = table.parent / (CPU+'-'+kind+'.rpt')
        raw = path.read_bytes(); text = raw.decode('ascii').replace('\r\n','\n')
        one = ROUTED['one']; portable = ROUTED['synth'].portable
        command = one(r'^\| Command\s*: (.+)$',text).strip()
        prefix = f'report_timing -to {CPU} -delay_type {kind} -max_paths 8 -nworst 1 -input_pins -nets -file '
        require(command.startswith(prefix) and portable(command[len(prefix):])==portable(path.resolve()) and one(r'^\| Design State\s*:\s*(.+)$',text).strip()=='Routed', 'foreign or wrong-stage historical detail')
        src = [r for r in rows if (r['destination_clock'],r['kind'])==(CPU,kind)][:8]
        details = re.split(r'(?m)(?=^Slack \((?:MET|VIOLATED)\)\s*:)',text)[1:]
        require(len(src)==len(details)==8,'truncated historical path detail')
        for r, block in zip(src,details):
            state,ns = one(r'^Slack \((MET|VIOLATED)\)\s*:\s*(-?\d+\.\d+)ns',block)
            fields = [one('^  '+field+r':\s+(\S+)\s*$',block) for field in ('Source', 'Destination','Path Group')]
            require(fields==[r['from'],r['to'],CPU] and ns==r['slack_ns'] and (state=='VIOLATED')==(Decimal(ns)<0), 'legacy path detail differs from table')
        ids[kind+'_detail'] = hashed(raw)
    return ids


def audit(run, log, kit=None):
    blob = log.read_bytes()
    pinfile = run / 'tight_setup_hold_pins.txt'; raw = pinfile.read_bytes()
    dcp = run / 'obj/post_route.dcp'
    if kit is None:
        scope = 'Historical 100 MHz Rocket diagnostic: Explore route only, without post-route phys_opt or bitstream.'
        table = run / 'routed-endpoints/endpoints.tsv'
        ids = dict(log=hashed(blob), pins=hashed(raw), endpoints=digest(table), dcp=digest(dcp))
        require(ids == LEGACY, 'different historical Rocket artifacts')
        val = json.loads((DOC/'validation.json').read_bytes())['stock_route_only']
        require(all(digest(run/'obj/report'/n) == h for n,h in val['reports_sha256'].items()), 'different published routed reports')
    else:
        scope = 'Four-wide BOOM: original post-route physical optimization, CPU capture samples only; not signoff.'
        ref = json.loads((DOC/'perf-mega175-initial-congestion.json').read_bytes())
        cut = ref['native_log_prefix_bytes']
        require(len(blob)>=cut and hashed(blob[:cut])==ref['native_log_prefix_sha256'] and hashed(raw)==ref['native_tight_pins_sha256'], 'different four-wide initial route')
        require(dcp.is_file() and (run/'obj/routed-endpoints/endpoints.tsv').is_file(), 'final four-wide DCP and endpoint sample not yet available')
        anchor = ROUTED['mega'](run,kit,log)
        require(anchor['board_input_seal']==ref['board_input_seal'], 'different four-wide build')
        table = run / 'obj/routed-endpoints/endpoints.tsv'
        ids = dict(log_prefix=hashed(blob[:cut]), pins=hashed(raw), endpoints=anchor['report_hashes'][table.name], dcp=anchor['post_route_dcp_sha256'])
    pins = initial(blob.decode(errors='replace').replace('\r\n','\n'), raw.decode('ascii'))
    data = table.read_bytes(); require(hashed(data)==ids['endpoints'], 'changed final endpoint table')
    samples = join(pins,data)
    if kit is None:
        ids.update(legacy_details(table,data))
        for kind, check in [('max','setup'),('min','hold')]:
            require(Decimal(samples[kind]['worst_slack_ns']) == Decimal(str(val['timing'][check]['slack_ns'])), 'different historical worst slack')
    return dict(scope=scope, sha256=ids, initial_pins=len(pins), capture_clock=CPU, final_samples=samples)


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run',type=Path); ap.add_argument('log',type=Path)
    ap.add_argument('--four-wide-kit',type=Path,help='required for the four-wide build; otherwise only the pinned historical Rocket control is accepted')
    args=ap.parse_args(); print(json.dumps(audit(args.run,args.log,args.four_wide_kit), indent=2))
