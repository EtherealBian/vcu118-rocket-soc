#!/usr/bin/env python3
"""Rebuild both architectural probes and compare independent stock/LVT pin captures.

The stock CPU simulation package and its physical-shell package have different
manifests. Bind both to the published physical input verification. Never reads
from hardware and never emits a CoreMark score.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
PROBE = runpy.run_path(str(HERE/'check-mega-regfile-chiptop.py'))
DOCS = HERE.parent/'docs'


def compare(stock, lvt, base_seal, lvt_seal):
    for rec, role, seal in [(stock, 'stock', base_seal), (lvt, 'lvt', lvt_seal)]:
        if (rec['role'] != role or rec['kit_seal'] != seal or rec['wrong_expected_value_rejected'] is not True
                or rec['valid']['mode'] != 'single' or rec['valid']['frame_bytes'] != rec['fixtures']['good']['frame_bytes']):
            raise ValueError('wrong model or missing check')
    if base_seal == lvt_seal or any(stock[k] == lvt[k] for k in ('model_sha256','model_archive_sha256')):
        raise ValueError('models are not distinct')
    for k in ('rom_dtb_sha256','sources','fixtures','wrong_immediate_offset','valid'):
        if stock[k] != lvt[k]: raise ValueError('different program, ROM, receiver or pin witness: '+k)
    for k in ('elf_sha256','payload_sha256','frame_sha256'):
        if stock['fixtures']['good'][k] == stock['fixtures']['wrong'][k]: raise ValueError('identical fault control')
    if stock['fixtures']['good']['frame_bytes'] != stock['fixtures']['wrong']['frame_bytes']:
        raise ValueError('wrong check changed frame length')


def audit(stock_kit,stock_pins,stock_run,lvt_kit,lvt_pins,lvt_run):
    rows = []
    for role,kit,pins,out in [('stock',stock_kit,stock_pins,stock_run),('lvt',lvt_kit,lvt_pins,lvt_run)]:
        rec=PROBE['exercise'](role,kit,pins,out,review_only=True)
        if rec != json.loads((out/'result.json').read_bytes()):raise ValueError('independent review differs: '+role)
        rows.append(rec)
    phys=json.loads((DOCS/'perf-mega175-implementation-inputs.json').read_bytes())
    alt=json.loads((DOCS/'perf-mega175-regfile-input.json').read_bytes())
    fixed=DOCS/'perf-mega175-fixed-rom-link.json'
    if (phys['board_input_seal']!=alt['stock_board_seal'] or phys['corrected_pin_review']!=sha256(fixed.read_bytes()).hexdigest()):
        raise ValueError('stock CPU and physical kit provenance disagree')
    compare(*rows,json.loads(fixed.read_bytes())['inputs']['CANDIDATE.sha256'],alt['candidate_board_input_seal'])
    pinrows=[json.loads((d/'result.json').read_bytes()) for d in (stock_pins,lvt_pins)]
    for key in ('harts','ticks_per_bit','wrong_rate_ticks_rejected','valid_frame','corrupt_frame','rom_dtb_sha256'):
        if pinrows[0][key]!=pinrows[1][key]:raise ValueError('parent ROM controls differ: '+key)
    cc=Path(os.getenv('VCU_TOOLS', Path.home()/'.local/share/vcu118-tools'))/'bootlin/bin/riscv64-linux-gcc'
    return dict(scope='Four-wide functional ChipTop with behavioral TL memory. Same two 8N1 frames in stock and LVT; not a proof of general CPU equivalence, FPGA timing, Linux or physical performance.',
                stock_physical_seal=phys['board_input_seal'],candidate_physical_seal=alt['candidate_board_input_seal'],
                rom_dtb_sha256=rows[0]['rom_dtb_sha256'],compiler=subprocess.check_output([cc,'-dumpfullversion'],text=True).strip(),
                compiler_flags=PROBE['GCC'],sources=rows[0]['sources'],fixtures=rows[0]['fixtures'],
                controlled_change=dict(payload_offset=rows[0]['wrong_immediate_offset'],expected=264,wrong_expected=265),
                original_rom_controls={k:pinrows[0][k] for k in ('harts','ticks_per_bit','wrong_rate_ticks_rejected','valid_frame','corrupt_frame')},
                models={r['role']:{k:r[k] for k in ('kit_seal','model_sha256','model_archive_sha256','valid','wrong_expected_value_rejected')} for r in rows})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('stock_kit','stock_pins','stock_run','lvt_kit','lvt_pins','lvt_run'):p.add_argument(arg,type=Path)
    a=p.parse_args();print(json.dumps(audit(*(v.resolve() for v in vars(a).values())),indent=2))
