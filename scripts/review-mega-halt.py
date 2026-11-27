#!/usr/bin/env python3
"""Independently rebuild the four-wide halt overlay and replay both debug-module traces."""
import argparse
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
fixture = ROOT/'tests/debug_halt_sources.cpp'

def digest(f): return sha256(f.read_bytes()).hexdigest()

def review(original, modified, old_run, new_run, control100=None):
    derive = runpy.run_path(str(HERE/'derive-mega-halt-model.py'))['derive']
    verify = runpy.run_path(str(HERE/'check-model-kit.py'))['check']
    compare = runpy.run_path(str(HERE/'compare-halt-traces.py'))['compare']
    shape = runpy.run_path(str(HERE/'check-boom-shape.py'))['check'](original/'rtl',4,128)
    records = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp); clone = tmp/'re-derived'
        with redirect_stdout(io.StringIO()): derive(original, clone, control100)
        if (clone/'CANDIDATE.sha256').read_bytes() != (modified/'CANDIDATE.sha256').read_bytes():
            raise ValueError('cannot re-derive candidate from stock')
        for kit, out in ((original,old_run),(modified,new_run)):
            expected = {p.resolve() for p in (kit/'CANDIDATE.sha256',out/'sim',fixture)}
            for row in (out/'inputs.sha256').read_text().splitlines():
                h,n = row.split('  ',1); p=(ROOT/n).resolve(strict=True)
                if p not in expected or digest(p)!=h: raise ValueError('changed or unexpected capture input')
                expected.remove(p)
            if expected: raise ValueError('capture input missing')
            vf = out/'verFiles.dat'; commands = [r[3:-1] for r in vf.read_text().splitlines() if r.startswith('C "') and r.endswith('"')]
            if len(commands)!=1: raise ValueError('ambiguous build command')
            cmd=shlex.split(commands[0]); top='--top-module'
            if cmd.count(top)!=1 or cmd[cmd.index(top)+1]!='TLDebugModule' or str(fixture) not in cmd:
                raise ValueError('wrong Verilator top or testbench')
            (tmp/'VChipTop__verFiles.dat').write_bytes(vf.read_bytes())
            verify(tmp,kit)  # all HDL paths, hashes, inodes and timestamps against this actual invocation
            replay=tmp/'replay.bin'; cp=subprocess.run([str((out/'sim').resolve()),str(replay)],check=True,capture_output=True)
            if cp.stdout!=(out/'result.txt').read_bytes() or replay.read_bytes()!=(out/'events.bin').read_bytes():
                raise ValueError('archived traces do not replay')
            if cp.stdout.splitlines()[-1:] != [b'GENERATED_DEBUG_HALT_SOURCES_PASS clock_cases=9']:
                raise ValueError('not a completed run')
            replay.unlink()
            records.append(dict(kit_sha256=digest(kit/'CANDIDATE.sha256'),fixture_sha256=digest(fixture),simulation_sha256=digest(out/'sim'),
                                debug_rtl_sha256=digest(kit/'rtl/TLDebugModule.sv'),trace_sha256=digest(out/'events.bin')))
        ticks, deltas = compare(old_run, new_run)
    if records[0]['trace_sha256']==records[1]['trace_sha256'] or records[0]['debug_rtl_sha256']==records[1]['debug_rtl_sha256']:
        raise ValueError('identical trace or debug module')
    return dict(scope='Four-wide BOOM debug module only, functional RTL with asynchronous clock phase cases. Not CDC signoff, a routed clock, Linux, or a CoreMark score.',
                decoded_lanes=shape['decoder_count'],rob_entries=shape['rob_entries'],clock_cases=9,transactions_per_case=16,
                registered_delay_in_debug_edges=2,observations=ticks,observably_delayed=deltas,original=records[0],candidate=records[1])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('original','modified','old_run','new_run'): p.add_argument(key,type=Path)
    p.add_argument('--control100',type=Path); a=p.parse_args()
    print(json.dumps(review(*(q.resolve(strict=True) for q in (a.original,a.modified,a.old_run,a.new_run)),a.control100),indent=2))
