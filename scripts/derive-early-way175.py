#!/usr/bin/env python3
"""Recreate the three-wide 175 MHz way-select experiment from three sealed model kits.

This is a derived *functional* kit, not a fresh Scala elaboration or board build.
The stock kit owns the clock and boot contract; only the tested D-cache is replaced.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent
DOC = HERE.parent/'docs'
CONE = runpy.run_path(str(HERE/'check-mshr-way-cone.py'))
READ = runpy.run_path(str(HERE/'derive-mega-halt-model.py'))['read']
CLOCK = runpy.run_path(str(HERE/'check-wide-clock-delta.py'))['check']
MANIFEST = 'CANDIDATE.sha256'
MODULE = 'rtl/BoomNonBlockingDCache.sv'


def transplant(stock, changed_module, original_hash, candidate_hash):
    if (original_hash == candidate_hash or sha256(stock[MODULE]).hexdigest() != original_hash
            or sha256(changed_module).hexdigest() != candidate_hash):
        raise ValueError('unqualified way-select donor or clocked recipient')
    return {**stock, MODULE: changed_module}


def derive(low, donor, high, out, tool):
    if out.exists(): raise ValueError('fresh experiment directory required')
    cone_record = json.loads((DOC/'perf-early-way-cone.json').read_bytes())
    clock_record = json.loads((DOC/'perf175-hdl-delta.json').read_bytes())
    kits = (low, donor, high)
    seals = [sha256((k/MANIFEST).read_bytes()).hexdigest() for k in kits]
    if seals[:2] != cone_record['kit_seals'] or [seals[0],seals[2]] != clock_record['inputs']:
        raise ValueError('not the qualified three-way input matrix')
    low_files, donor_files, high_files = map(READ, kits)
    if CLOCK(low, high) != clock_record or CONE['compare_inputs'](low, donor) != cone_record['hdl_comparison']:
        raise ValueError('clock or cache axis differs from published comparison')
    if MODULE in clock_record['changes'] or low_files[MODULE] != high_files[MODULE]:
        raise ValueError('clock and cache changes overlap')
    files = transplant(high_files, donor_files[MODULE], *cone_record['module_sha256'])
    base = 'chipyard.fpga.vcu118.VCU118FPGATestHarness.Perf175LargeBoomVCU118Config'
    gen = HERE.parent/'third_party/chipyard/fpga/generated-src'/base
    dts = gen/(base+'.dts')
    if (files['board.dts'] != dts.read_bytes() or any(files['rtl/'+s] != (gen/'gen-collateral'/s).read_bytes()
            for s in ('TLROM.sv','DigitalTop.sv'))):
        raise ValueError('generated boot hardware differs from recipient')
    subprocess.run([sys.executable,str(HERE/'check-board-dt.py'),str(dts),'--rom',str(high/'rom/sdboot.elf'),
                    '--mhz','175','--harts','1'],check=True,stdout=subprocess.DEVNULL)
    out.mkdir(); kit = out/'derived-model'; kit.mkdir()
    for name,data in files.items():
        dst = kit/name; dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(data)
    (kit/MANIFEST).write_bytes(''.join(f'{sha256(data).hexdigest()}  {name}\n' for name,data in sorted(files.items())).encode())
    reread = READ(kit)
    if reread.keys() != high_files.keys() or [k for k in reread if reread[k] != high_files[k]] != [MODULE]:
        raise ValueError('unexpected output model delta')
    a,b = [CONE['generate'](k,out/tag,tool) for k,tag in ((high,'stock-ast'),(kit,'derived-ast'))]
    checked = CONE['check_cones'](a,b)
    if any(cone_record[k] != v for k,v in checked.items()): raise ValueError('175 MHz cone proof differs')
    return dict(scope='Derived three-wide functional HDL only: stock 175 MHz request plus the qualified early-way D-cache, not an independent elaboration, timing result, or board score.',
                stock100_donor100_stock175_seals=seals, derived175_seal=sha256((kit/MANIFEST).read_bytes()).hexdigest(),
                stock175_ordered_hdl_files=len(files['sources.f'].splitlines()), changed_from_stock175=[MODULE],
                dcache_sha256=cone_record['module_sha256'], stock175_source_order_rom_dt_config_preserved=True,
                board_contract='Stock generated single-hart DT/RTC, PLL request, ROM image and handoff checked; no physical PLL measurement.',
                verilator=subprocess.check_output([tool,'--version'],text=True).strip(), **checked)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('stock100','donor100','stock175','out'): p.add_argument(name,type=Path)
    p.add_argument('--verilator',default='verilator'); a = p.parse_args()
    result = derive(a.stock100,a.donor100,a.stock175,a.out,a.verilator)
    (a.out/'review.json').write_text(json.dumps(result,indent=2)+'\n')
