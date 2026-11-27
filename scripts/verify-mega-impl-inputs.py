#!/usr/bin/env python3
"""Reject raw, stale or mismatched inputs before starting a four-wide 175 MHz implementation."""
from hashlib import sha256
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import subprocess

HERE=Path(__file__).resolve().parent
TOP='rtl/VCU118FPGATestHarness.sv'
STEM='board/chipyard.fpga.vcu118.VCU118FPGATestHarness.Perf175MegaBoomVCU118Config.'

def h(p):return sha256(p.read_bytes()).hexdigest()

def seals(kit):
    kit=kit.resolve(strict=True); sums={}
    for row in (kit/'CANDIDATE.sha256').read_text(encoding='ascii').splitlines():
        m=re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_./-]+)',row)
        if not m:raise ValueError('bad seal syntax')
        digest,k=m.groups(); rel=PurePosixPath(k)
        if k in sums or k=='CANDIDATE.sha256' or rel.is_absolute() or '..' in rel.parts or rel.as_posix()!=k:raise ValueError('repeated or invalid seal member')
        p=kit/k
        if p.resolve(strict=True)!=p or h(p)!=digest:raise ValueError('changed sealed input: '+k)
        sums[k]=digest
    actual={p.relative_to(kit).as_posix() for p in kit.rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=set(sums)|{'CANDIDATE.sha256'}:raise ValueError('unlisted input (including optional XDC)')
    return sums

def model_seal(sums, top, stem, overlay):
    # Undo ONLY the physical wrapper substitution, then reconstruct every byte
    # digest in the functional manifest from the actual implementation kit.
    members={k:v for k,v in sums.items() if k.startswith('rtl/') or k in ('sources.f','rom/sdboot.elf','rom/sdboot.bin')}
    members[TOP]=top; members['config.scala']=sums[overlay]; members['board.dts']=sums[stem+'dts']
    seal=''.join(f'{d}  {k}\n' for k,d in sorted(members.items()))
    return sha256(seal.encode()).hexdigest()

def shell_review(sums, report):
    roles=report['cases']; fixed=roles['fixed']; original=roles['raw']
    expected=[(5000,1025,517),(2857,1025,517)]
    for record,stages in ((original,0),(fixed,2)):
        cases=[(p['half_period_ps'],p['samples'],p['different_from_other_latency']) for p in record['positive']]
        if cases != expected or record['expected_stages']!=stages or record['wrong_latency_rejected']!=2:
            raise ValueError('incomplete pad-to-ChipTop RX controls')
    leaves=('AnalogToUInt_1.v','UIntToAnalog_1.v','PowerOnResetFPGAOnly.v','plusarg_reader.v')
    for leaf in (*leaves,'VCU118FPGATestHarness.sv'):
        if sums.get('rtl/'+leaf)!=fixed['inputs'][leaf]: raise ValueError('shell simulation differs from physical input: '+leaf)
    for leaf in (*leaves,'shell_rx_tb.v','boundaries.v'):
        if original['inputs'][leaf]!=fixed['inputs'][leaf]: raise ValueError('unmatched RX comparison')
    if fixed['inputs']['shell_rx_tb.v']!=h(HERE.parent/'tests/shell_rx_tb.v'): raise ValueError('RX fixture changed')


def check_recipe(kit,sums):
    rev=(kit/'implementation-revision.txt').read_text().strip()
    if not re.fullmatch('[0-9a-f]{40}',rev): raise ValueError('bad implementation revision')
    subprocess.run(['git','merge-base','--is-ancestor',rev,'HEAD'],cwd=HERE.parent,check=True)
    def file(name):
        b=subprocess.check_output(['git','show',rev+':scripts/'+name],cwd=HERE.parent)
        if sums.get(name)!=sha256(b).hexdigest(): raise ValueError('wrong implementation recipe: '+name)
        return b
    if b'require-no-comb-loops.tcl' in file('implement.tcl'): file('require-no-comb-loops.tcl')
    return rev

def verify(kit,run):
    sums=seals(kit)
    overlay=runpy.run_path(str(HERE/'board_shell_overlay.py'))['PINS']; merge=runpy.run_path(str(HERE/'prepare-halt-merge.py'))
    pll=runpy.run_path(str(HERE/'promote-wide-model.py'))['pll_expected']
    for key,want in zip((TOP,STEM+'shell.xdc','shell/xilinx/common/tcl/synth.tcl'),[p[1] for p in overlay]):
        if sums.get(key)!=want:raise ValueError('not the corrected physical shell')
    for suffix,digest in [('shell.sdc','6dddf8745955b694762781deb78dd4b0483f15daef50dd8f680ae8db6350d2e1'),('shell.vivado.tcl','2523542e19fb8b963af43d54131bf5edd04720a6e04a3a0e25151388e8daac06'),('vcu118mig.vivado.tcl','c55dde01f37c8297c69f3ab933718e4a0633568f103cd9e3ab3570a3d11e3fdc')]:
        if sums.get(STEM+suffix)!=digest:raise ValueError('wrong board clock, IO or MIG recipe')
    rx=HERE.parent/'docs/perf-physical-rx.json'
    shell_review(sums,json.loads(rx.read_bytes())); rev=check_recipe(kit,sums)
    # Lock the PLL completely, including its tolerance checks, not just its displayed request.
    ref='chipyard.fpga.vcu118.VCU118FPGATestHarness.RocketVCU118Config'
    path=HERE.parent/'third_party/chipyard/fpga/generated-src'/ref/(ref+'.harnessSysPLL.vivado.tcl')
    if h(path)!='50aafc268d0a8cb38dce048e82e9f0ca38145e9635ed45451933d3b7b6d87512' or (kit/(STEM+'harnessSysPLL.vivado.tcl')).read_bytes()!=pll(path.read_bytes(),175):raise ValueError('PLL not pinned to 175 MHz')
    read=lambda name:json.loads((run/name).read_bytes()); halt=read('halt.json'); orig=read('stock-pin.json'); fix=read('fix-pin.json')
    if (halt['decoded_lanes'],halt['rob_entries'],halt['clock_cases'],halt['transactions_per_case'],halt['registered_delay_in_debug_edges'])!=(4,128,9,16,2) or not 0<halt['observably_delayed']<halt['observations']:raise ValueError('incomplete exact debug qualification')
    if orig['inputs']['CANDIDATE.sha256']==fix['inputs']['CANDIDATE.sha256'] or orig['rom_dtb_sha256']!=fix['rom_dtb_sha256']:raise ValueError('wrong model pair or changed boot ROM')
    for role,pin,label in [('original',orig,'stock'),('candidate',fix,'halt')]:
        seal=(kit/(label+'-model-seal.txt')).read_text().strip()
        if not re.fullmatch('[0-9a-f]{64}',seal) or seal!=pin['inputs']['CANDIDATE.sha256'] or seal!=halt[role]['kit_sha256']:raise ValueError('mixed pin, halt and implementation inputs')
        if (pin['harts'],pin['uart_pbus_design_mhz'],pin['ticks_per_bit'],pin['wrong_rate_ticks_rejected'],pin['valid_frame']['mode'],pin['corrupt_frame']['mode'])!=(1,175,1519,868,'single','crc') or sums['rom/sdboot.bin']!=pin['inputs']['sdboot.bin']:raise ValueError('wrong ROM-link evidence')
    if model_seal(sums,overlay[0][0],STEM,'overlay/Perf175MegaBoom.scala')!=fix['inputs']['CANDIDATE.sha256']:
        raise ValueError('implementation does not reproduce the entire tested functional kit')
    model=merge['MEGA_PINS']; changed={'TLDebugModule'}
    if any(sums.get('rtl/'+n+'.sv')!=d for n,d in model.items() if n not in changed) or sums['rtl/TLDebugModule.sv']!=halt['candidate']['debug_rtl_sha256'] or sums.get('rtl/'+merge['NAME']+'.sv')!=h(HERE.parent/'rtl/clocking'/(merge['NAME']+'.sv')):raise ValueError('not the tested four-wide debug graph')
    sources=(kit/'sources.f').read_text().splitlines()
    if len(sources)!=len(set(sources)) or {k for k in sums if k.startswith('rtl/')}!=set(sources) or len(sources)<300:raise ValueError('incomplete HDL list')
    if sums.get('overlay/Perf175MegaBoom.scala')!=h(HERE.parent/'rtl/perf/Perf175MegaBoom.scala'):raise ValueError('incorrect processor configuration')
    return dict(scope='Private implementation input check only; no synthesized/routed or hardware claims.',family='Mega',physical_harts_in_dts=1,decode_lanes=4,rob_entries=128,pll_request_mhz=175,hdl_sources=len(sources),board_input_seal=h(kit/'CANDIDATE.sha256'),implementation_revision=rev,physical_rx_review=h(rx),halt_review=h(run/'halt.json'),stock_pin_review=h(run/'stock-pin.json'),corrected_pin_review=h(run/'fix-pin.json'))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('run',type=Path);a=p.parse_args();print(json.dumps(verify(a.kit,a.run),indent=2))
