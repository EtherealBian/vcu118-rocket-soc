#!/usr/bin/env python3
"""Run the same two-process guest and three deliberately wrong guests under QEMU virt.
Only a newly created regular-file ext4 fixture is attached, read-only; no root or board.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PASS = 'LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d'
CASES = ('good', 'bad-fp', 'bad-page', 'bad-atomic')


def change(text, old, new):
    if text.count(old) != 1:
        raise ValueError('negative control no longer matches production source')
    return text.replace(old, new)


def run(fw, out):
    out.mkdir()
    tools = Path(os.environ.get('VCU_TOOLS', Path.home()/'.local/share/vcu118-tools'))
    cc = tools/'bootlin/bin/riscv64-linux-gcc'
    src = ROOT/'software/oscheck'
    c = (src/'check.c').read_text(); asm = (src/'exchange.S').read_text()
    q = tools/'qemu'; env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = f'{q}/usr/lib/x86_64-linux-gnu:{q}/lib/x86_64-linux-gnu:'+env.get('LD_LIBRARY_PATH','')
    with tempfile.TemporaryDirectory() as temp:
        tmp = Path(temp); media = tmp/'root'; media.mkdir(); img = tmp/'media.img'
        binaries = {}
        for name in CASES:
            # Corrupt one result *within* the guest, leaving its acceptance checks intact.
            cs = change(c, 'set_page(1+child);', 'set_page(1+child); if(child)cow[99]^=1;') if name=='bad-page' else c
            ss = asm
            if name=='bad-fp':
                ss = change(asm,'.Lcheck:\n','.Lcheck:\n beqz t2,1f\n addi a6,t5,1\n bne a6,t3,1f\n fadd.s ft1,ft1,ft3\n1:\n')
            if name=='bad-atomic':
                ss = change(asm,' amoadd.d.aqrl zero,a5,(t4)',' nop')
            (tmp/'check.c').write_text(cs); (tmp/'exchange.S').write_text(ss)
            binary=media/name
            subprocess.run([cc,'-Os','-Wall','-Wextra','-Werror','-march=rv64gc','-mabi=lp64d','-static','-s','-Wl,--build-id=none',tmp/'check.c',tmp/'exchange.S','-o',binary],check=True)
            binaries[name]=hashlib.sha256(binary.read_bytes()).hexdigest()
        if len(set(binaries.values())) != len(CASES):raise ValueError('fixture binaries not distinct')
        with img.open('xb') as f:f.truncate(16<<20)
        subprocess.run(['mke2fs','-q','-F','-t','ext4','-d',media,img],check=True)
        args=[q/'usr/bin/qemu-system-riscv64','-machine','virt','-smp','1','-m','256M','-nographic','-monitor','none','-bios',fw,'-drive',f'file={img},format=raw,readonly=on,if=none,id=osd','-device','virtio-blk-device,drive=osd']
        nonce=secrets.token_hex(7); tags=[f'OS_{n}_' for n in CASES]; sent=False; data=b''
        with subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,bufsize=0) as proc, (out/'uart.txt').open('xb') as log:
            try:
                with selectors.DefaultSelector() as sel:
                    sel.register(proc.stdout,selectors.EVENT_READ); end=time.monotonic()+120
                    while time.monotonic()<end:
                        if not sel.select(1):continue
                        chunk=os.read(proc.stdout.fileno(),8192)
                        if not chunk:raise RuntimeError('UART closed')
                        log.write(chunk);log.flush();data+=chunk
                        if len(data)>512000 or b'Kernel panic' in data:raise RuntimeError('unexpected console')
                        if not sent and b'SOC_CHECK_PASS bytes=16777216' in data and re.search(rb'(?:^|\n)# $',data):
                            shell='mkdir /tmp/ost && mount -t ext4 -o ro /dev/vda /tmp/ost && { '+''.join('/tmp/ost/'+n+'; echo '+tag+'$?_'+nonce+'; ' for n,tag in zip(CASES,tags))+'}\n'
                            proc.stdin.write(shell.encode());proc.stdin.flush();sent=True
                        if sent and re.search(rb'^OS_bad-atomic_\d+_'+nonce.encode()+rb'\r?\n',data,re.M):break
                lines=data.decode('ascii',errors='replace').splitlines()
                expected=[PASS]+[tag+str(code)+'_'+nonce for tag,code in zip(tags,(0,5,5,5))]
                events=[s for s in lines if s==PASS or re.fullmatch(r'OS_[\w-]+_\d+_'+nonce,s)]
                if events!=expected:raise ValueError('guest result sequence failed: '+str(events))
            finally:
                proc.terminate()
                try:proc.wait(timeout=4)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
    record=dict(firmware_sha256=hashlib.sha256(fw.read_bytes()).hexdigest(),guest_sha256=binaries,expected_exit_codes=dict(zip(CASES,(0,5,5,5))),uart_sha256=hashlib.sha256(data).hexdigest(),machine='QEMU virt, single hart, read-only ext4 fixture')
    (out/'results.json').write_text(json.dumps(record,indent=2)+'\n');print('QEMU_OSCHECK_AND_THREE_NEGATIVE_CONTROLS_PASS')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('firmware',type=Path);ap.add_argument('out',type=Path);a=ap.parse_args();run(a.firmware.resolve(strict=True),a.out)
