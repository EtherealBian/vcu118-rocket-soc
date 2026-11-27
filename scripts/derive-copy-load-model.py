#!/usr/bin/env python3
"""Seal one experimental functional model; never edit or start the routed board build."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import shutil

HERE=Path(__file__).resolve().parent
C=runpy.run_path(str(HERE/'test-copy-load-rename.py'))
seals=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']
MAN='CANDIDATE.sha256'; LEAF='rtl/RenameStage.sv'
def h(data):return sha256(data).hexdigest()


def only_one(old,new,expected):
    if new!={**old,LEAF:expected} or LEAF not in old or old[LEAF]==expected:
        raise ValueError('expected exactly one distinct rename-stage substitution')


def build(kit,tested,out):
    kit=kit.resolve(strict=True);tested=tested.resolve(strict=True);out=out.resolve()
    if out.exists() or any(x in out.parents or out in x.parents for x in (kit,tested)): raise ValueError('fresh separate output required')
    ref=json.loads((HERE.parent/'docs/perf-strict-user-lvt.json').read_bytes())['designs']['stock'][MAN]
    if h((kit/MAN).read_bytes())!=ref: raise ValueError('expected the original functional kit, not a board variant')
    old=seals(kit); leaf=C['candidate']((kit/LEAF).read_bytes().decode()).encode()
    fixture=json.loads((tested/'result.json').read_bytes()); proof=json.loads((HERE.parent/'docs/perf-copy-load-rename.json').read_bytes())
    if (fixture!=proof or h(leaf)!=fixture['candidate_sha256'] or (tested/'RenameStage.sv').read_bytes()!=leaf or
        h((tested/'wiring.svh').read_bytes())!=fixture['wiring_sha256'] or h((HERE.parent/'tests/copy_load_rename_tb.v').read_bytes())!=fixture['bench_sha256']):
        raise ValueError('unmatched local paired-RTL test')
    for name,verdict in fixture['results'].items():
        expected='COPYLOAD_RENAME_PASS cases=22' if name=='candidate' else verdict
        if (tested/(name+'.txt')).read_text().strip()!=expected: raise ValueError('missing exact fixture verdict')
    ordered=(kit/'sources.f').read_text().splitlines()
    if ordered.count(LEAF)!=1 or len(ordered)!=len(set(ordered)) or len(ordered)!=549: raise ValueError('wrong source order')
    shutil.copytree(kit,out);(out/LEAF).write_bytes(leaf)
    new={k:h((out/k).read_bytes()) for k in old};only_one(old,new,h(leaf))
    (out/MAN).write_bytes(''.join(f'{v}  {k}\n' for k,v in sorted(new.items())).encode())
    if seals(out)!=new or seals(kit)!=old or h((kit/MAN).read_bytes())!=ref: raise ValueError('kit changed during derivation')
    return dict(scope='Functional source inputs only; not a compiled model, physical input, or board result.',original_seal=ref,
                candidate_seal=h((out/MAN).read_bytes()),ordered_hdl=len(ordered),sealed_members=len(new),changed={LEAF:h(leaf)})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('stock','paired_test','fresh_out'):p.add_argument(k,type=Path)
    a=p.parse_args();print(json.dumps(build(a.stock,a.paired_test,a.fresh_out),indent=2))
