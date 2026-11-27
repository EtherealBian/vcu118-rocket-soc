#!/usr/bin/env python3
"""Exercise the same three shell commands with the pinned image on QEMU virt.

Expect the strict ELF's two CRCs to match but the BOOM machine check to FAIL.
This is a protocol control, never a boot of the generated chip or board.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import subprocess
import time

from mega_linux_shell_review import ROOT, commands, one, benchmark, machine


def run(firmware, qemu, out):
    ref=json.loads((ROOT/'docs/perf-mega175-linux-entry.json').read_bytes())
    if sha256(firmware.read_bytes()).hexdigest()!=ref['inputs']['fw_payload.bin']:
        raise ValueError('need the same stock firmware')
    out.mkdir(mode=0o700); nonce=secrets.token_hex(7); cmd=commands(nonce)
    env=dict(os.environ); env['LD_LIBRARY_PATH']=':'.join([str(qemu/sub) for sub in ('usr/lib/x86_64-linux-gnu','lib/x86_64-linux-gnu')]+[env.get('LD_LIBRARY_PATH','')])
    args=[qemu/'usr/bin/qemu-system-riscv64','-machine','virt','-smp','1','-m','256M','-nographic','-monitor','none','-bios',firmware]
    raw=bytearray(); stop=time.monotonic()+90
    with subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=0,env=env) as proc,selectors.DefaultSelector() as sel:
        sel.register(proc.stdout,selectors.EVENT_READ)
        def wait(pattern,offset):
            while time.monotonic()<stop and len(raw)<262144:
                m=re.search(pattern,raw[offset:],re.M)
                if m:return offset+m.end()
                if sel.select(.2):
                    data=os.read(proc.stdout.fileno(),8192)
                    if not data:break
                    raw.extend(data)
            raise ValueError('no expected QEMU console reply: '+str(pattern))
        try:
            end=wait(rb'^LINUX_OSCHECK_PASS [^\r\n]+\r?\n',0)
            for line,marker in zip(cmd,('LIVE','MACHINE_END','DONE')):
                prompt=wait(rb'^# $',end)
                proc.stdin.write((line+'\n').encode());proc.stdin.flush()
                end=wait(f'^CM_{marker}_42_{nonce}\\r?\\n'.encode(),prompt)
        finally:
            proc.terminate();proc.wait(timeout=5)
            (out/'qemu.uart').write_bytes(raw);(out/'nonce').write_text(nonce+'\n')
    rows=raw[:end].decode('ascii').replace('\r','').splitlines(); hits=[one(rows,c) for c in cmd]
    if hits!=sorted(hits) or not hits[0]<one(rows,'CM_LIVE_42_'+nonce)<hits[1]:
        raise ValueError('wrong command epoch')
    crcs=benchmark(rows,nonce,ref['embedded_benchmark']['elf_sha256'])
    try:
        machine.inspect(rows,hits[1],hits[2],nonce,nonce,machine.MEGA_SEAL)
    except ValueError as exc:
        if str(exc)!='expected one online BOOM CPU and hart 0':raise
    else:
        raise ValueError('QEMU falsely accepted as the BOOM model')
    return dict(scope='QEMU virt shell protocol control only; not BOOM RTL or hardware.',
                strict_elf_sha256=ref['embedded_benchmark']['elf_sha256'],iterations_per_seed=4,
                final_crcs=crcs,boom_machine_identity_accepted=False,uart_sha256=sha256(raw).hexdigest())


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('firmware','qemu','out'):ap.add_argument(name,type=Path)
    args=ap.parse_args(); result=run(args.firmware.resolve(),args.qemu.resolve(),args.out.resolve())
    text=json.dumps(result,indent=2)+'\n'; (args.out/'control.json').write_text(text);print(text,end='')
