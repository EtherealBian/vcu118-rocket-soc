#!/usr/bin/env python3
"""Validate a hardware Linux shell profile. Raw /proc outputs and console stay local."""
import argparse, hashlib, json, re
from decimal import Decimal
from pathlib import Path


def parse(raw, nonce, host_ms=None):
    if not re.fullmatch('[0-9a-f]{14}',nonce): raise ValueError('invalid challenge')
    s=raw.decode('ascii').replace('\r\n','\n'); lines=s.splitlines()
    def marker(tag):
        opts=[i for i,v in enumerate(lines) if v==tag or (tag.startswith(('LIVE_', 'BEGIN_')) and v=='# '+tag)]
        if len(opts)!=1: raise ValueError('missing or repeated marker '+tag)
        return opts[0]
    tags=['LIVE_42_'+nonce,'BEGIN_42_'+nonce,'NAME','CPU','MEM','UP1','IRQ1','LOAD','STATUS_0','UP2','IRQ2','END_42_'+nonce]; indices=[marker(t) for t in tags]
    if indices!=sorted(indices): raise ValueError('out-of-order console')
    sections={a:'\n'.join(lines[i+1:j]) for a,i,j in zip(tags,indices,indices[1:])}
    def match(expr,sec):
        vals=re.findall(expr,sections[sec],re.M)
        if len(vals)!=1: raise ValueError('bad '+sec+' field: '+expr)
        return vals[0]
    # This profile is for the full-memory 6.6.65 firmware, not QEMU or the diagnostic mem=128M variant.
    if not re.fullmatch(r'Linux 6\.6\.65 riscv64',sections['NAME']): raise ValueError('unexpected uname')
    proc=match(r'^processor\s*:\s*(\d+)$','CPU'); hart=match(r'^hart\s*:\s*(\d+)$','CPU'); isa=match(r'^isa\s*:\s*(rv64\w+)$','CPU'); mmu=match(r'^mmu\s*:\s*(\w+)$','CPU'); arch=match(r'^uarch\s*:\s*([^\n]+)$','CPU')
    if (proc,hart,mmu,arch)!=('0','0','sv39','sifive,rocket0') or not set('imafdc')<=set(isa.split('_')[0][4:]):raise ValueError('unexpected hart or ISA')
    kib=int(match(r'^MemTotal:\s+(\d+) kB$','MEM')); passes,sec=map(int,match(r'^SOC_CHECK_PASS bytes=16777216 passes=(\d+) elapsed_s=(\d+)$','LOAD'))
    def uptime(section): return Decimal(match(r'^(\d+\.\d+) \d+\.\d+$',section))
    wall=uptime('UP2')-uptime('UP1'); timer=[int(match(r'^\s*\d+:\s+(\d+)[^\n]*\briscv-timer\s*$',x)) for x in ('IRQ1','IRQ2')]
    if not (1800*1024<=kib<2*1024*1024 and passes>0 and 15<=sec<=90 and abs(wall-sec)<4 and timer[1]>timer[0]):raise ValueError('unexpected memory, duration or IRQ progression')
    if host_ms is not None and (host_ms <= 0 or abs(wall-Decimal(host_ms)/1000)>Decimal('1.0')):
        raise ValueError('guest uptime disagrees with monotonic host UART observation')
    return dict(host_observation_ms=host_ms,kernel='6.6.65',machine='riscv64',hart=0,mmu=mmu,uarch=arch,linux_reported_isa=isa,memtotal_kib=kib,userspace_bytes=16777216,write_read_passes=passes,guest_elapsed_integer_seconds=sec,uptime_window_seconds=str(wall),timer_interrupt_delta=timer[1]-timer[0],console_sha256=hashlib.sha256(raw).hexdigest(),scope='one Linux process touching an allocated 16 MiB buffer, not a peak memory bandwidth or full capacity test')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('console',type=Path); ap.add_argument('nonce'); ap.add_argument('--host-ms',type=int,required=True); a=ap.parse_args(); print(json.dumps(parse(a.console.read_bytes(),a.nonce,a.host_ms),indent=2))
