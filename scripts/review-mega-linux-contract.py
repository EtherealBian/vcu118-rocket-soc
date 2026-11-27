#!/usr/bin/env python3
"""Derive the *expected* live Linux identity from the four-wide implementation ROM.

This offline contract cannot register a bitstream, attest a running board, or
approve timing. Use /proc/cpuinfo and sysfs on the *new* boot for a separate
live check; the cpu@0 clock-frequency placeholder is not the system PLL.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
MACHINE_PROPERTIES={
    '/cpus/timebase-frequency':(175000).to_bytes(4,'big'),
    '/cpus/cpu@0/compatible':b'ucb-bar,boom0\x00riscv\x00',
    '/soc/pbus_clock/clock-frequency':(175000000).to_bytes(4,'big'),
}

def identity(raw):
    if raw!=MACHINE_PROPERTIES:raise ValueError('unexpected immutable boot properties')
    return {'/sys/firmware/devicetree/base'+name:sha256(data).hexdigest() for name,data in raw.items()}

def review(kit):
    saved=json.loads((HERE.parent/'docs/perf-mega175-implementation-inputs.json').read_bytes()); seal=sha256((kit/'CANDIDATE.sha256').read_bytes()).hexdigest();
    if seal!=saved['board_input_seal']:raise ValueError('not the implementation package')
    runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals'](kit)
    # Includes reconstruction of the ROM initialization from the actual TLROM RTL.
    rom=runpy.run_path(str(HERE/'review-clocked-rom-link.py'))['verify_kit_clock'](kit,175,1)
    if rom!=json.loads((HERE.parent/'docs/perf-mega175-fixed-rom-link.json').read_bytes())['rom_dtb_sha256']:raise ValueError('ROM differs from the pin-qualified fixed model')
    source,=(kit/'board').glob('*.dts')
    with tempfile.TemporaryDirectory() as tmp:
        dtb=Path(tmp)/'boot.dtb';subprocess.run(['dtc','-q','-I','dts','-O','dtb','-o',dtb,source],check=True)
        def prop(mode,node,key):return subprocess.check_output(['fdtget','-t',mode,dtb,node,key],text=True).strip()
        raw={path:bytes(int(b,16) for b in prop('bx',*path.rsplit('/',1)).split()) for path in MACHINE_PROPERTIES}; live=identity(raw)
        alias=prop('s','/chosen','stdout-path'); ph=prop('u','/soc/pbus_clock','phandle')
        if prop('u',alias,'clocks')!=ph or prop('u','/cpus/cpu@0','clock-frequency')!='0' or prop('u','/cpus/cpu@0','timebase-frequency')!='175000':raise ValueError('wrong UART clock binding or unexpected per-hart clock')
        dtb_hash=sha256(dtb.read_bytes()).hexdigest(); isa=prop('s','/cpus/cpu@0','riscv,isa')
    return dict(scope='Static expectation from the exact four-wide implementation ROM. Not a live Linux boot, timing closure or permission to program.',board_input_seal=seal,rom_and_dtb_sha256=rom,dtb_only_sha256=dtb_hash,expected_online_cpu='0',expected_hart=0,expected_uarch='ucb-bar,boom0',firmware_isa=isa,declared_pbus_hz=175000000,declared_timebase_hz=175000,cpu_node_clock_placeholder_hz=0,live_property_sha256=live)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);a=p.parse_args();print(json.dumps(review(a.kit.resolve()),indent=2))
