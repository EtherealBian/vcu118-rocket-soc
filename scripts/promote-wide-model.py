#!/usr/bin/env python3
"""Promote a sealed three-wide functional model to PRIVATE VCU118 build inputs, never to hardware."""
import argparse
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'chipyard.fpga.vcu118.VCU118FPGATestHarness.'
BOARD_FILES = ('shell.xdc', 'shell.sdc', 'vcu118mig.vivado.tcl', 'shell.vivado.tcl')


def pll_expected(reference, mhz):
    if mhz not in (100, 175): raise ValueError('unexpected design frequency')
    # Do not permit an arbitrary PLL edit or a wider acceptance band.
    low, high = mhz * 99 / 100, mhz * 101 / 100
    for old, new in [('CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {100.0}', f'CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {{{mhz:.1f}}}'),
                     ('$freq < 99.0 || $freq > 101.0', f'$freq < {low} || $freq > {high}'),
                     ('range 99.0-101.0', f'range {low}-{high}')]:
        if reference.count(old.encode()) != 1:
            raise ValueError('unknown reference PLL input')
        reference = reference.replace(old.encode(), new.encode())
    return reference


def promote(kit, obj, mhz, dest):
    cy = ROOT/'third_party/chipyard'; fp = cy/'fpga'; shell = fp/'fpga-shells'
    stem = {100:'PerfLargeBoom', 175:'Perf175LargeBoom'}[mhz]
    def generated(stem): return fp/'generated-src'/(PREFIX+stem+'VCU118Config')
    gen, stock = generated(stem), generated('Rocket'); kit = kit.resolve()
    def board(d, ext): return d/(d.name+'.'+ext)
    def verify(*args, cwd=ROOT): subprocess.run(args, cwd=cwd, check=True)
    verify('sha256sum','--quiet','-c','CANDIDATE.sha256',cwd=kit)
    verify(sys.executable, ROOT/'scripts/check-model-kit.py', obj, kit)
    verify(sys.executable, ROOT/'scripts/check-board-dt.py', board(gen,'dts'), '--rom',kit/'rom/sdboot.elf','--mhz',str(mhz))
    verify(sys.executable, ROOT/'scripts/check-boom-shape.py', kit/'rtl', '--width','3','--rob-entries','96')
    verify(sys.executable, ROOT/'scripts/check-debug-clock.py', stock/'gen-collateral/ChipTop.sv',kit/'rtl/ChipTop.sv')
    verify(sys.executable, ROOT/'scripts/check-debug-buffer.py', stock/'gen-collateral',kit/'rtl')
    members = {}
    def put(k,v):
        if k in members: raise ValueError('duplicate member: '+k)
        members[k] = v.read_bytes() if isinstance(v, Path) else v
    paths = [Path(row).resolve(strict=True) for row in board(gen,'vsrcs.f').read_text().splitlines() if row]
    names = ['rtl/'+p.name for p in paths]; manifest = (kit/'sources.f').read_bytes()
    if len(paths)<300 or len(set(names))!=len(names) or names!=manifest.decode().splitlines(): raise ValueError('HDL list mismatch')
    for key,file in zip(names,paths):
        if cy not in file.parents or file.read_bytes()!=(kit/key).read_bytes(): raise ValueError('generated HDL differs: '+key)
        put(key,kit/key)
    put('sources.f',manifest)
    for ext in BOARD_FILES+('harnessSysPLL.vivado.tcl','dts','memmap.json','l2.json'):
        path=board(gen,ext); data=path.read_bytes()
        if ext in BOARD_FILES and data!=board(stock,ext).read_bytes(): raise ValueError('board pin/clock/MIG constraints differ: '+ext)
        if ext=='harnessSysPLL.vivado.tcl' and data!=pll_expected(board(stock,ext).read_bytes(),mhz): raise ValueError('unexpected PLL changes')
        if ext=='dts' and data!=(kit/'board.dts').read_bytes(): raise ValueError('simulated DT mismatch')
        put('board/'+path.name,data)
    overlay=ROOT/'rtl/perf'/(stem+'.scala')
    if overlay.read_bytes()!=(kit/'config.scala').read_bytes(): raise ValueError('different configuration source')
    put('overlay/'+overlay.name,overlay)
    for suffix in ('elf','bin'): put('rom/sdboot.'+suffix,kit/('rom/sdboot.'+suffix))
    for folder in ('xilinx/common/tcl','xilinx/vcu118'):
        for f in (shell/folder).rglob('*'):
            if f.is_file(): put('shell/'+f.relative_to(shell).as_posix(),f)
    route='shell/xilinx/common/tcl/route.tcl'; data=members[route]
    if sha256(data).hexdigest()!='7130014d70130776967d591797e4b34a64c8c4d4c26d955db629d828463b54b3':raise ValueError('unknown upstream route recipe')
    cmd=b'route_design -directive Explore\n'
    members[route]=data.replace(cmd,cmd+b'write_checkpoint [file join $wrkdir routed_before_physopt.dcp]\n')+b'''
report_bus_skew -file [file join $wrkdir routed-bus-skew.rpt]
report_io -file [file join $wrkdir routed-io.rpt]
source [file join $scriptdir vcu-endpoints.tcl]
vcu_endpoint_reports [file join $wrkdir routed-endpoints]
'''
    put('shell/xilinx/common/tcl/vcu-endpoints.tcl',ROOT/'scripts/diagnose-routed.tcl')
    # Select one committed implementation recipe, never a partially edited worktree.
    recipe_rev=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    def recipe(name):
        return subprocess.check_output(['git','show',recipe_rev+':scripts/'+name],cwd=ROOT)
    put('implement.tcl',recipe('implement.tcl'))
    if b'require-no-comb-loops.tcl' in members['implement.tcl']:
        put('require-no-comb-loops.tcl',recipe('require-no-comb-loops.tcl'))
    put('implementation-revision.txt',(recipe_rev+'\n').encode())
    for label,folder in [('chipyard',cy),('fpga-shells',shell),('boom',cy/'generators/boom')]:
        for f in folder.glob('LICENSE*'):
            if f.is_file(): put('notices/'+label+'/'+f.name,f)
    put('THIRD-PARTY.md',ROOT/'THIRD-PARTY.md')
    dest.mkdir()  # never merge with an old kit; write the manifest LAST
    for name,data in members.items():
        out=dest/name; out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(data)
    (dest/'CANDIDATE.sha256').write_bytes(''.join(f'{sha256(v).hexdigest()}  {k}\n' for k,v in sorted(members.items())).encode())
    verify('sha256sum','--quiet','-c','CANDIDATE.sha256',cwd=dest)
    print(f'PRIVATE_BOARD_INPUTS_MATCH_SIMULATED_HDL mhz_request={mhz} sources={len(paths)}; NOT_PLACED_ROUTED_OR_PROGRAMMED')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('obj',type=Path);p.add_argument('mhz',type=int,choices=[100,175]);p.add_argument('dest',type=Path);a=p.parse_args();promote(a.kit,a.obj,a.mhz,a.dest)
