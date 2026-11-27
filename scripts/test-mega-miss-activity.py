#!/usr/bin/env python3
"""Read the late integer miss select on the exact recovery ChipTop; never drive internal signals."""
import argparse
import json
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
C = runpy.run_path(str(HERE/'test-mega-recovery-linux.py'))
F, need, h, doc, write, ROOT = [C[k] for k in ('F','need','h','doc','write','ROOT')]


def source(base):
    text=base.read_text()
    for key,extra in [('#include "VChipTop___024root.h"','\n#include "mega_miss_activity.hpp"'),
                      ('const auto &r = *t.rootp;', '\n    MissActivity activity(r);'),
                      ('      t.clock_uncore = 1;', ''), ('          trace.close();', '\n          activity.finish();')]:
        need(text.count(key)==1,'unexpected observer boundary')
        text=text.replace(key, ('      if (active) activity.sample();\n' if not extra else '')+key+extra)
    return text


def main():
    a=argparse.ArgumentParser(description=__doc__); a.add_argument('mode',choices=('run','review'))
    for name in ('physical','kit','previous','guest','elf','verilator','out'): a.add_argument(name,type=Path)
    a=a.parse_args(); physical,kit,prev,guest,elf,vt=[getattr(a,k).resolve(strict=True) for k in ('physical','kit','previous','guest','elf','verilator')]
    need(not a.out.is_symlink(),'symlink out'); out=a.out.resolve(); obj=C['qualified'](physical,kit,prev,vt)
    ref=doc(C['PREVIOUS']); need(h(elf)==ref['elf_sha256'],'wrong ELF'); pins=json.loads((prev/'inputs.json').read_bytes()); env=F['tool_env'](vt)
    need(F['hashes'](F['shared'](guest,obj))==doc('perf-strict-user-lvt.json')['shared_inputs'],'changed snapshots or harness')
    harness=ROOT/'tests/mega_user_replay.cpp'; header=ROOT/'tests/mega_miss_activity.hpp'
    deps={k:pins[k] for k in F['PAIR']['HARNESS']}; need(h(harness)==deps[harness.name],'reference harness drift')
    if a.mode=='run':
        F['owned_output'](out,kit,[physical,kit,prev,guest,elf,vt,HERE,ROOT/'tests',ROOT/'docs']); out.mkdir(mode=0o700)
        (out/'observer.cpp').write_text(source(harness)); (out/header.name).write_bytes(header.read_bytes())
        F['LINK'](out/'observer.cpp',out/'model',obj,vt/'share/verilator/include',env=env)
    need((out/'observer.cpp').read_text()==source(harness) and h(out/header.name)==h(header),'observer drift')
    bound={'physical':ref['pair']['candidate_sha256'],'archive':ref['candidate_archive_sha256'],'elf':h(elf),'inputs':h(prev/'inputs.json'),
           **{p.name:h(p) for p in (header,out/'observer.cpp',obj/'VChipTop_VcuIntMissSlot.h',out/'model')}}
    if a.mode=='run':
        write(out/'bound.json',bound)
        for seed,s in ref['results'].items():
            d=out/seed; d.mkdir(); ram=guest/seed/'replay'
            with (d/'uart').open('xb') as u,(d/'events').open('xb') as e:
                subprocess.run([out/'model',ram/'mem.bin',ram/'prefix.frame',str(s['arch_instructions']),d/'pc'],cwd=d,env=env,stdout=u,stderr=e,check=True,timeout=3600)
            print('REPLAY_EXITED '+seed,flush=True)
    need(bound==json.loads((out/'bound.json').read_bytes()),'binary/input drift')
    rv=runpy.run_path(str(HERE/'review-mega-miss-activity.py'))['review']
    results={seed:rv(out/seed,s) for seed,s in ref['results'].items()}
    result=dict(scope='Recovery ChipTop RTL, two strict four-round user snapshots, pre-edge Boolean dependence; not delay, IPC loss, or board CoreMark/s.',bound=bound,results=results)
    if a.mode=='run': write(out/'result.json',result)
    else: need(json.loads((out/'result.json').read_bytes())==result,'review mismatch')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
