#!/usr/bin/env python3
"""Check an architectural int/FP probe over a four-wide model's ROM UART pins.

Requires the exact stock or derived kit and a separately recorded valid+fault
ROM link run. No internal register peeking, timing qualification or board score.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from uart_frame import encode
rom = runpy.run_path(str(HERE/'review-clocked-rom-link.py'))
ASM = ROOT/'software/boot-uart/regfile-probe.S'
LD = ROOT/'software/bare/layout.ld'
GCC = ['-nostdlib','-static','-no-pie','-fno-pie','-march=rv64imafdc_zicsr',
       '-mabi=lp64d','-mno-relax','-Wl,--build-id=none']

def digest(p): return sha256(p.read_bytes()).hexdigest()

def seal(role):
    if role == 'stock':
        return json.loads((ROOT/'docs/perf-mega175-fixed-rom-link.json').read_bytes())['inputs']['CANDIDATE.sha256']
    if role == 'lvt':
        return json.loads((ROOT/'docs/perf-mega175-regfile-input.json').read_bytes())['candidate_board_input_seal']
    raise ValueError('unknown role')

def one_immediate(good, wrong, offset):
    # addi t1,x0,264 -> addi t1,x0,265 at the exported expected-value symbol.
    ins = (0x10800313).to_bytes(4,'little'); alt = (0x10900313).to_bytes(4,'little')
    if (not 0 <= offset <= len(good)-4 or offset % 4 or good[offset:offset+4] != ins or
            wrong != good[:offset]+alt+good[offset+4:]):
        raise ValueError('negative fixture modified more than the one expected immediate')

def fixtures(directory):
    cc = str(Path(os.environ.get('VCU_TOOLS', Path.home()/'.local/share/vcu118-tools'))/'bootlin/bin/riscv64-linux-')
    rows = {}; words = []; offsets = []
    for bias,name in enumerate(('good','wrong')):
        elf = directory/(name+'.elf'); binary = directory/(name+'.bin'); frame = directory/(name+'.frame')
        subprocess.run([cc+'gcc',*GCC,f'-DRF_EXPECT_BIAS={bias}','-T',LD,ASM,'-o',elf],check=True)
        subprocess.run([cc+'objcopy','-O','binary',elf,binary],check=True)
        nm = subprocess.check_output([cc+'nm','-n',elf],text=True)
        def address(symbol):
            hits = re.findall(r'^([0-9a-f]+) T '+symbol+'$',nm,re.M)
            if len(hits)!=1: raise ValueError('missing/duplicate symbol: '+symbol)
            return int(hits[0],16)
        start=address('_start'); offsets.append(address('rf_expected_lane6')-start)
        words.append(binary.read_bytes()); payload = encode(words[-1]); frame.write_bytes(payload)
        if start!=0x80000000 or not 16<len(payload)<=2048: raise ValueError('bad fit to pin harness')
        rows[name] = dict(elf_sha256=digest(elf),payload_sha256=digest(binary),frame_sha256=digest(frame),frame_bytes=len(payload))
    if offsets[0]!=offsets[1]: raise ValueError('control moved check point')
    one_immediate(*words,offsets[0]); return rows, offsets[0]

def model(role,kit,pins):
    if digest(kit/'CANDIDATE.sha256')!=seal(role): raise ValueError('wrong sealed kit')
    pin = rom['review'](pins,kit,175,'single')
    original = json.loads((ROOT/'docs/perf-mega175-fixed-rom-link.json').read_bytes())
    if (pin != json.loads((pins/'result.json').read_bytes()) or
        (role=='stock' and pin!=original) or pin['rom_dtb_sha256']!=original['rom_dtb_sha256']):
        raise ValueError('unmatched input, ROM or independent pin control')
    for key in ('probe.elf','probe.frame','crc.frame','rom_link.cpp','rocket_chiptop.cpp','sdboot.bin'):
        if pin['inputs'][key]!=original['inputs'][key]: raise ValueError('different original pin fixture: '+key)
    return pin

def exercise(role,kit,pins,out,review_only=False):
    pin=model(role,kit,pins); exe=pins/'model'
    if not review_only: out.mkdir()
    with tempfile.TemporaryDirectory() as tmp:
        fdir=Path(tmp) if review_only else out; rows,offset=fixtures(fdir)
        for name in rows:
            if review_only:
                for suffix in ['elf','bin','frame']:
                    path=name+'.'+suffix
                    if (out/path).read_bytes()!=(fdir/path).read_bytes(): raise ValueError('probe not reproducible: '+path)
            else:
                proc=subprocess.run([exe,'175',out/(name+'.frame'),'single'],capture_output=True,timeout=3600)
                (out/(name+'.stdout')).write_bytes(proc.stdout); (out/(name+'.stderr')).write_bytes(proc.stderr)
                (out/(name+'.code')).write_text(str(proc.returncode)+'\n')
    def got(n,s): return (out/(n+'.'+s)).read_bytes()
    if got('good','code')!=b'0\n' or got('good','stderr') or got('wrong','code')!=b'1\n' or got('wrong','stdout') or got('wrong','stderr')!=b'unexpected UART byte\n':
        raise ValueError('expected valid pin trace and rejection specifically at the UART byte checker')
    trace=rom['read_pass'](got('good','stdout').decode('ascii'),'single',rows['good']['frame_bytes'],1519)
    if digest(exe)!=pin['inputs']['model'] or digest(kit/'CANDIDATE.sha256')!=seal(role): raise ValueError('pin model changed')
    return dict(scope='Bare-metal ChipTop pin simulation with external behavioral RAM. Eight integer and eight double recurrence lanes, single precision check; no board, Linux, timing or CoreMark result.',role=role,kit_seal=seal(role),rom_dtb_sha256=pin['rom_dtb_sha256'],model_sha256=digest(exe),model_archive_sha256=pin['inputs']['VChipTop__ALL.a'],sources={'assembly':digest(ASM),'linker_script':digest(LD),'pin_harness':pin['inputs']['rom_link.cpp']},fixtures=rows,wrong_immediate_offset=offset,wrong_expected_value_rejected=True,valid=trace)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('role',choices=('stock','lvt'))
    for n in ('kit','pins','out'): p.add_argument(n,type=Path)
    p.add_argument('--review-only',action='store_true');a=p.parse_args();r=exercise(a.role,a.kit.resolve(),a.pins.resolve(),a.out.resolve(),a.review_only)
    print(json.dumps(r,indent=2))
