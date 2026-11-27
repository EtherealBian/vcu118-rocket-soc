#!/usr/bin/env python3
"""Clone a stock four-wide BOOM model with the registered debug-halt fix. Not a board kit."""
import argparse
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent
MERGE = runpy.run_path(str(HERE/'prepare-halt-merge.py'))
SYNC = runpy.run_path(str(HERE/'annotate-irq-sync.py'))
MANIFEST = 'CANDIDATE.sha256'


def read(kit):
    files = {}
    for line in (kit/MANIFEST).read_text().splitlines():
        m = re.fullmatch(r'([a-f0-9]{64})  ([\w./-]+)', line)
        if not m: raise ValueError('invalid seal record')
        digest, name = m.groups(); p = PurePosixPath(name)
        if p.is_absolute() or p.as_posix() != name or '..' in p.parts or name in files or name == MANIFEST:
            raise ValueError('unexpected seal member: '+name)
        path = kit/name
        if not path.is_file() or path.resolve() != path.absolute(): raise ValueError('missing or linked member: '+name)
        data = path.read_bytes()
        if sha256(data).hexdigest() != digest: raise ValueError('modified input: '+name)
        files[name] = data
    sources = files['sources.f'].decode().splitlines()
    if len(sources)<300 or len(set(sources))!=len(sources) or not all(re.fullmatch(r'rtl/[\w.-]+\.(?:sv|v)',n) for n in sources):
        raise ValueError('unexpected HDL source list')
    if set(files) != set(sources)|{'sources.f','rom/sdboot.elf','rom/sdboot.bin','config.scala','board.dts'}:
        raise ValueError('not a sealed functional kit')
    return files


def validate_clock_pair(control, stock):
    if control is None: raise ValueError('175 MHz requires the 100 MHz stock Mega control')
    delta = runpy.run_path(str(HERE/'check-wide-clock-delta.py'))['check']
    delta(control, stock, 'Mega')
    for kit,mhz,stem in ((control,100,'PerfMegaBoom'),(stock,175,'Perf175MegaBoom')):
        files = read(kit)
        if files['config.scala']!=(HERE.parent/'rtl/perf'/(stem+'.scala')).read_bytes():
            raise ValueError('incorrect reference clock or family')
        base = 'chipyard.fpga.vcu118.VCU118FPGATestHarness.'+stem+'VCU118Config'
        gen = HERE.parent/'third_party/chipyard/fpga/generated-src'/base
        # Check the *same* ROM+DT against the generated TLROM, the ELF handoff,
        # RTC divider and generated PLL. A filename or clock-only diff is insufficient.
        dts = gen/(base+'.dts'); gd = gen/'gen-collateral'
        if (files['board.dts']!=dts.read_bytes() or any(files['rtl/'+n]!=(gd/n).read_bytes() for n in ('TLROM.sv','DigitalTop.sv'))):
            raise ValueError('sealed boot contract differs from generated input')
        subprocess.run([sys.executable,str(HERE/'check-board-dt.py'),str(dts),'--rom',str(kit/'rom/sdboot.elf'),'--mhz',str(mhz)],check=True,stdout=subprocess.DEVNULL)


def derive(stock, dest, control100=None):
    if dest.exists(): raise ValueError('fresh output directory required')
    files = read(stock)
    if files['config.scala'] == (HERE.parent/'rtl/perf/Perf175MegaBoom.scala').read_bytes():
        validate_clock_pair(control100, stock)
    elif control100 is not None or files['config.scala'] != (HERE.parent/'rtl/perf/PerfMegaBoom.scala').read_bytes():
        raise ValueError('expected a stock four-wide overlay')
    MERGE['require_graph'](MERGE['MEGA_PINS'], lambda name: sha256(files['rtl/'+name+'.sv']).hexdigest())
    leaf = 'rtl/'+SYNC['NAME']; marked = SYNC['annotated'](files[leaf]); dest.mkdir()
    for name,data in files.items():
        out=dest/name; out.parent.mkdir(exist_ok=True,parents=True); out.write_bytes(marked if name==leaf else data)
    MERGE['install'](dest)
    added='rtl/'+MERGE['NAME']+'.sv'; manifest = (dest/'sources.f').read_text().splitlines()
    if [k for k in manifest if k!=added] != files['sources.f'].decode().splitlines() or manifest.count(added)!=1:
        raise ValueError('unexpected source list changes')
    sums={}; changed=set()
    for name in [*files, added]:
        data=(dest/name).read_bytes(); sums[name]=sha256(data).hexdigest()
        if data!=files.get(name): changed.add(name)
    if changed!={added,leaf,'rtl/TLDebugModule.sv','sources.f'}: raise ValueError('unaccounted model delta')
    (dest/MANIFEST).write_bytes(''.join(f'{digest}  {name}\n' for name,digest in sorted(sums.items())).encode())
    read(dest)
    print('FOUR_WIDE_HALT_MODEL_ONLY',sha256((dest/MANIFEST).read_bytes()).hexdigest())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('stock',type=Path); p.add_argument('dest',type=Path)
    p.add_argument('--control100',type=Path); a=p.parse_args(); derive(a.stock.resolve(strict=True),a.dest.resolve(),a.control100)
