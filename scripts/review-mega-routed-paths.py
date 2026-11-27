#!/usr/bin/env python3
"""Locate the slow CPU-clock endpoints in the current run, including failed routes.

Read-only failure triage, not frequency qualification. A file from a different
run cannot be used just by copying its report into this run's directory.
"""
import argparse
import csv
from decimal import Decimal
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('footprint', HERE / 'review-boom-synth-footprint.py')
synth = importlib.util.module_from_spec(spec); spec.loader.exec_module(synth)
CLOCK = 'clk_out1_harnessSysPLL'


def one(pattern, text):
    out = re.findall(pattern, text, re.M)
    if len(out) != 1:
        raise ValueError('missing/ambiguous report field: ' + pattern)
    return out[0]


def parse_pair(path, text, rows, kind):
    cmd = one(r'^\| Command\s*: (.+)$', text).strip()
    prefix = f'report_timing -to {CLOCK} -delay_type {kind} -max_paths 8 -nworst 1 -input_pins -file '
    if not cmd.startswith(prefix) or synth.portable(cmd[len(prefix):]) != synth.portable(path.resolve()):
        raise ValueError('wrong report command or implementation run')
    for field, value in [('Design State','Physopt postRoute'),('Design','VCU118FPGATestHarness'),('Device','xcvu9p-flga2104')]:
        if one(r'^\| '+field+r'\s*: (.*)$',text).strip()!=value: raise ValueError('wrong '+field)
    if len(rows)!=40 or len({r['to'] for r in rows})!=40:
        raise ValueError('expected 40 distinct endpoints')
    slacks = [Decimal(r['slack_ns']) for r in rows]
    if any(not s.is_finite() for s in slacks) or slacks!=sorted(slacks): raise ValueError('unsorted or invalid slack')
    detail = re.split(r'(?m)(?=^Slack \((?:MET|VIOLATED)\)\s*:)',text)[1:]
    if len(detail)!=8: raise ValueError('expected eight detailed paths')
    checked=[]
    for d, row in zip(detail,rows):
        def get(key, pat): return one(r'^  '+key+r':[ \t]+'+pat,d)
        source=get('Source',r'(\S+)\n[^\n]*?clocked by (\S+)\s+\{[^}]*?period=([\d.]+)ns\}')
        dest=get('Destination',r'(\S+)\n[^\n]*?clocked by (\S+)\s+\{[^}]*?period=([\d.]+)ns\}')
        state,slack=one(r'^Slack \((MET|VIOLATED)\)\s*:\s*([-\d.]+)ns',d)
        levels=int(get('Logic Levels',r'(\d+)')); group=get('Path Group',r'(\S+)'); typ=get('Path Type',r'(\S+)')
        if ((source[0],dest[0])!=(row['from'],row['to']) or dest[1]!=CLOCK or group!=CLOCK or
            typ!=('Setup' if kind=='max' else 'Hold') or Decimal(slack)!=Decimal(row['slack_ns']) or
            (Decimal(slack)<0)!=(state=='VIOLATED') or levels!=int(row['logic_levels'])):
            raise ValueError('path/table identity, type or sign mismatch')
        data,logic,routing=get('Data Path Delay',r'([\d.]+)ns\s+\(logic ([\d.]+)ns \([\d.]+%\)\s+route ([\d.]+)ns \([\d.]+%\)\)')
        if abs(Decimal(data)-Decimal(logic)-Decimal(routing))>Decimal('.002'): raise ValueError('component delay mismatch')
        checked.append(dict(launch=source[0],capture=dest[0],launch_clock=source[1],capture_clock=dest[1],capture_period_ns=dest[2],slack_ns=slack,logic_levels=levels,logic_ns=logic,routing_ns=routing,data_ns=data))
    return dict(sampled_endpoints=40,unique_launches=len({r['from'] for r in rows}),negative_in_sample=sum(s<0 for s in slacks),details=checked)


def cpu_paths(obj):
    p=obj/'routed-endpoints'; table=p/'endpoints.tsv'; raw=table.read_bytes(); hashes={table.name:sha256(raw).hexdigest()}
    rows=list(csv.DictReader(io.StringIO(raw.decode()),delimiter='\t')); result={}
    for kind in ('max','min'):
        path=p/f'{CLOCK}-{kind}.rpt'; raw=path.read_bytes(); hashes[path.name]=sha256(raw).hexdigest()
        result[kind]=parse_pair(path,raw.decode().replace('\r\n','\n'),[r for r in rows if (r['destination_clock'],r['kind'])==(CLOCK,kind)],kind)
    return result,hashes


def mega(run, kit, log):
    run=run.resolve(); obj=run/'obj'; sealed=json.loads((HERE.parent/'docs/perf175-synth-footprint.json').read_bytes())['four_wide_split']
    if synth.review(log,kit,obj/'post_synth.dcp',synth.SEALS[1])!=sealed: raise ValueError('different synthesis')
    tail=log.read_text(errors='replace').split('\nVCU118_STAGE=route\n')
    if len(tail)!=2:raise ValueError('missing route stage')
    dcp=obj/'post_route.dcp'; target=one(r"^INFO: \[Common 17-1381\] The checkpoint '([^']+/post_route.dcp)' has been generated\.$",tail[1]);
    if synth.portable(target)!=synth.portable(dcp.resolve()):raise ValueError('foreign routed checkpoint')
    paths,ids=cpu_paths(obj)
    if any(abs(Decimal(r['capture_period_ns'])-Decimal(1000)/175)>Decimal('.001') for v in paths.values() for r in v['details']):raise ValueError('different capture clock period')
    return dict(scope='Four-wide post-route CPU destination path sample, including failures. Not full STA, CDC, DRC or board qualification.',board_input_seal=sealed['board_input_seal'],post_route_dcp_sha256=synth.digest(dcp),report_hashes=ids,paths=paths)

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for n in ('run','kit','log'):a.add_argument(n,type=Path)
    x=a.parse_args();print(json.dumps(mega(x.run,x.kit,x.log),indent=2))
