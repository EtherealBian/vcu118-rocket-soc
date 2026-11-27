#!/usr/bin/env python3
"""Bind extra post-route reports to the sealed BOOM build. Never programs the board.

Run only after the main Vivado process has exited; each session is serial. Native
STA/CDC/DRC reports are collected on the unchanged design. Temporary 5 ns Gray
skew constraints are last, in a separate process that never writes a checkpoint.
"""
import argparse
import csv
from pathlib import Path
import json
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from routed_replay import compare_reports

paths = runpy.run_path(str(HERE/'review-mega-routed-paths.py'))
digest = paths['synth'].digest
REQUIRED = ('exceptions-coverage','exceptions-ignored','exceptions-ignored-objects',
            'waiver-definitions','cdc-with-waivers','waived-drc','waived-methodology',
            'utilization-by-slr','utilization-by-instance','high-fanout-by-slr','congestion',
            'cpu-max-characteristics','cpu-min-characteristics')


def reconcile(baseline, actual, kind):
    src=[(r['slack_ns'],r['from'],r['to']) for r in baseline if (r['destination_clock'],r['kind'])==(paths['CLOCK'],kind)]
    dst=[(r['slack_ns'],r['start'],r['end']) for r in actual]
    # Equal slack paths may change order. Different endpoints are not interchangeable.
    if len(src)!=40 or len(dst)!=40 or len({r[2] for r in src})!=40 or sorted(src)!=sorted(dst):
        raise ValueError('reopened checkpoint has different '+kind+' path sample')


def audit(run,kit,log,out,vivado):
    if out.exists(): raise ValueError('fresh output required')
    anchor=paths['mega'](run,kit,log); obj=run/'obj'; dcp=obj/'post_route.dcp'
    same=anchor['post_route_dcp_sha256']; out.mkdir(); extra=out/'routed'; gray=out/'gray'
    def run_tcl(script,sub,marker,*args):
        cmd=[str(vivado),'-mode','batch','-nojournal','-log',str(out/(sub.name+'.log')),
             '-source',str(HERE/script),'-tclargs',str(dcp),str(sub),*args]
        with (out/(sub.name+'.console')).open('wb') as f:
            subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,cwd=out,check=True)
        text=(out/(sub.name+'.log')).read_text(errors='replace')
        if text.splitlines().count(marker)!=1 or digest(dcp)!=same:
            raise ValueError('unfinished collection or changed checkpoint')
    run_tcl('inspect-mega-postroute.tcl',extra,'FOUR_WIDE_ROUTED_DIAGNOSTICS_COLLECTED_NOT_SIGNOFF')
    replay = compare_reports(obj/'report', extra/'replay')
    (out/'replay.json').write_bytes((json.dumps(dict(post_route_dcp_sha256=same, reports=replay), indent=2)+'\n').encode())
    if not all(row['matches'] for row in replay.values()):
        raise ValueError('original/reopened report mismatch; inspect replay.json and the native reports')
    hashes={}
    for n in REQUIRED:
        f=extra/(n+'.rpt')
        if not f.is_file() or not f.stat().st_size: raise ValueError('missing '+n)
        hashes[f.name]=digest(f)
    table=obj/'routed-endpoints/endpoints.tsv'
    if digest(table)!=anchor['report_hashes'][table.name]: raise ValueError('original endpoints changed')
    def rows(f):
        with f.open() as inp:return list(csv.DictReader(inp,delimiter='\t'))
    original=rows(table)
    for kind in ('max','min'):
        f=extra/f'cpu-{kind}.tsv'; reconcile(original,rows(f),kind); hashes[f.name]=digest(f)
    run_tcl('measure-mig-gray.tcl',gray,'MIG_GRAY_DIAGNOSTIC_SKEW_REPORT_COLLECTED','175')
    gray_files=[gray/n for n in ('bits.tsv','data-delays.tsv','bus-skew.rpt')]
    analyzer=runpy.run_path(str(HERE/'review-mig-gray.py'))['analyze']
    groups=analyzer(*(p.read_text() for p in gray_files))
    return dict(scope='Additional physical diagnostics only. Gray skew is temporary on a reopened design. Coverage, exception dispositions, I/O, waived and unwaived violations require review; no bitstream authorization.',
                board_input_seal=anchor['board_input_seal'],post_route_dcp_sha256=same,
                original_vs_reopened=replay,report_sha256=hashes,gray_input_sha256={p.name:digest(p) for p in gray_files},
                gray_transfers=groups,matched_cpu_endpoints={'max':40,'min':40})


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('run','kit','log','out','vivado'):ap.add_argument(arg,type=Path)
    a=ap.parse_args(); result=audit(*(getattr(a,k).resolve() for k in ('run','kit','log','out','vivado')))
    (a.out/'inventory.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('EXTRA_PHYSICAL_REPORTS_INVENTORIED_NOT_SIGNOFF')
