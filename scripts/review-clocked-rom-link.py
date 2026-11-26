#!/usr/bin/env python3
"""Recheck a ROM-link run against kit ROM+DT, clock and both pin-level fault controls (WSL)."""
import argparse
from hashlib import sha256
import json
import os
import sys
from pathlib import Path
import re
import subprocess
import tempfile
from uart_frame import encode
from quad_stage_trace import analyze


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def selected_period(mhz):
    return (mhz*1000000+57600)//115200


def read_pass(text, mode, frame_bytes, period):
    m = re.fullmatch(r'ROM_LINK_PASS mode=(\w+) bit_ticks=(\d+) edge_intervals=9 frame_bytes=(\d+) cycles=(\d+) quiet_bits=20\n',text)
    if not m or (m[1], int(m[2]), int(m[3])) != (mode, period, frame_bytes):
        raise ValueError('different mode, divider or incomplete frame/edge witness')
    cycles=int(m[4])
    if not 10*period*frame_bytes < cycles < 2000000+10*period*(frame_bytes+100):
        raise ValueError('pin run cycle count out of range')
    return dict(mode=mode, frame_bytes=frame_bytes, cycles=cycles)


def verify_kit_clock(kit, mhz, harts):
    candidates=[p for p in [kit/'board.dts', *(kit/'board').glob('*.dts')] if p.is_file()]
    if len(candidates)!=1: raise ValueError('expected one generated board DTS')
    with tempfile.TemporaryDirectory() as t:
        dtb=Path(t)/'board.dtb'; subprocess.run(['dtc','-q','-I','dts','-O','dtb','-o',str(dtb),str(candidates[0])],check=True)
        def fd(*args):return subprocess.check_output(['fdtget',*args[:1],str(dtb),*args[1:]],text=True).strip()
        cpus=[n for n in fd('-l','/cpus').splitlines() if n.startswith('cpu@')]
        if sorted(cpus)!=[f'cpu@{i}' for i in range(harts)]:raise ValueError('unexpected CPU nodes')
        for i in range(harts):
            p=f'/cpus/cpu@{i}'
            if fd('-tu',p,'reg')!=str(i) or fd('-ts',p,'status')!='okay': raise ValueError('offline or misnumbered hart')
        serial=fd('-ts','/chosen','stdout-path')
        def walk(p):
            yield p
            for c in fd('-l',p).splitlines():yield from walk(p.rstrip('/')+'/'+c)
        if 'sifive,uart0' not in fd('-ts',serial,'compatible').split():raise ValueError('unexpected UART')
        ph=fd('-tu',serial,'clocks'); clock=[]
        for p in walk('/'):
            if 'phandle' in fd('-p',p).splitlines() and fd('-tu',p,'phandle')==ph:
                clock.append(fd('-tu',p,'clock-frequency'))
        if clock!=[str(mhz*1000000)]: raise ValueError('UART clock does not match kit')
        payload=(kit/'rom/sdboot.bin').read_bytes()+dtb.read_bytes()
    rom=(kit/'rtl/TLROM.sv').read_text(); m=re.search(r"wire \[(1023|2047):0\]\[63:0\] _GEN =\s*'\{(.*?)\};",rom,re.S)
    if not m: raise ValueError('unknown TLROM packing')
    words=re.findall(r"64'h([0-9a-fA-F]+)",m[2]); raw=b''.join(int(w,16).to_bytes(8,'little') for w in reversed(words))
    if len(words)!=1+int(m[1]) or not raw.startswith(payload) or any(raw[len(payload):]): raise ValueError('ROM/DT differs from simulated RTL')
    return sha256(payload).hexdigest()


def review(out, kit, mhz, profile):
    if (mhz,profile) not in [(100,'single'),(150,'quad'),(175,'single')]:raise ValueError('unknown target')
    root=Path(__file__).resolve().parents[1]; out=out.resolve(); kit=kit.resolve()
    hashes={}; paths={}
    for line in (out/'inputs.sha256').read_text().splitlines():
        h,name=line.split('  ',1); p=Path(name); p=(root/p).resolve(strict=True)
        if p.name in hashes or digest(p)!=h:raise ValueError('input changed or repeated: '+p.name)
        hashes[p.name]=h; paths[p.name]=p
    required=[out/'model',kit/'CANDIDATE.sha256',kit/'rom/sdboot.bin',out/'probe/probe.elf',out/'probe/probe.frame',out/'crc.frame',root/'tests/rom_link.cpp',root/'tests/rocket_chiptop.cpp',*(root/'tests').glob('chiptop_*.hpp')]
    if profile=='quad':required.append(root/'tests/quad_stage_observer.hpp')
    if not all(paths.get(p.name)==p for p in required) or 'VChipTop__ALL.a' not in hashes or len(hashes)!=len(required)+1:raise ValueError('incomplete input identities')
    archive = paths['VChipTop__ALL.a']
    subprocess.run([sys.executable, str(root/'scripts/check-model-kit.py'), str(archive.parent), str(kit)],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['sha256sum','--quiet','-c','CANDIDATE.sha256'],cwd=kit,check=True)
    tools=Path(os.getenv('VCU_TOOLS',str(Path.home()/'.local/share/vcu118-tools')))
    with tempfile.TemporaryDirectory() as temp:
        binary=Path(temp)/'rebuilt.bin'
        subprocess.run([str(tools/'bootlin/bin/riscv64-linux-objcopy'),'-O','binary',str(out/'probe/probe.elf'),str(binary)],check=True)
        if binary.read_bytes()!=(out/'probe/probe.bin').read_bytes():raise ValueError('payload not from recorded probe ELF')
    harts=4 if profile=='quad' else 1
    contract=verify_kit_clock(kit,mhz,harts)
    good=(out/'probe/probe.frame').read_bytes(); fault=bytearray(encode(b'\x6f\x00\x00\x00'));fault[12]^=1
    if good!=encode((out/'probe/probe.bin').read_bytes()) or (out/'crc.frame').read_bytes()!=fault:raise ValueError('wrong UART fixture')
    period=selected_period(mhz); wrong=selected_period(175 if mhz==100 else 100)
    if (out/'wrong.txt').read_text()!=f'UART_EDGE_PERIOD_MISMATCH expected={wrong} observed={period}\n':raise ValueError('wrong-rate control not specifically rejected')
    lines=(out/'pass.txt').read_text().splitlines(keepends=True)
    if not lines: raise ValueError('missing positive test')
    extra={}
    if profile=='quad':
        nm=subprocess.check_output([str(tools/'bootlin/bin/riscv64-linux-nm'),'-n',str(out/'probe/probe.elf')],text=True)
        def symbol(name):
            hits=re.findall(r'^([0-9a-f]+) T '+name+'$',nm,re.M)
            if len(hits)!=1:raise ValueError('ambiguous trace region')
            return int(hits[0],16)
        extra['pipeline_trace']=analyze([s.rstrip('\n') for s in lines[:-1]],symbol('quad_trace_begin'),symbol('quad_trace_end'))
    elif len(lines)!=1:raise ValueError('unexpected single-hart output')
    return dict(scope='Functional ChipTop pin simulation, behavioral TL memory, ROM and DT checked against HDL. Not board, PLL, physical DDR or Linux validation.',harts=harts,uart_pbus_design_mhz=mhz,ticks_per_bit=period,first_byte_edge_intervals=9,wrong_rate_ticks_rejected=wrong,rom_dtb_sha256=contract,inputs=hashes,
                valid_frame=read_pass(lines[-1],profile,len(good),period),corrupt_frame=read_pass((out/'crc.txt').read_text(),'crc',len(fault),period),**extra)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('out',type=Path);ap.add_argument('kit',type=Path);ap.add_argument('mhz',type=int);ap.add_argument('profile',choices=['single','quad']);a=ap.parse_args();print(json.dumps(review(a.out,a.kit,a.mhz,a.profile),indent=2))
