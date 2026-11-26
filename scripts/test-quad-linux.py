#!/usr/bin/env python3
"""Positive four-hart and negative one-hart run of the same SMP Linux image (QEMU only)."""
import argparse, hashlib, json, os, re, secrets, selectors, subprocess, time
from pathlib import Path

PASS = 'QUAD_SMP_PASS pinned=0,1,2,3 workers=4 shared_handoffs=4096'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(n, release, out):
    q=Path(os.getenv('VCU_TOOLS',Path.home()/'.local/share/vcu118-tools'))/'qemu'
    env=dict(os.environ);env['LD_LIBRARY_PATH']=f'{q}/usr/lib/x86_64-linux-gnu:{q}/lib/x86_64-linux-gnu:'+env.get('LD_LIBRARY_PATH','')
    args=[q/'usr/bin/qemu-system-riscv64','-machine','virt','-m','256M','-smp',str(n),'-nographic','-monitor','none','-bios',release/'fw_payload.bin']
    uart=out/f'smp{n}.uart';nonce=secrets.token_hex(8);data=bytearray();deadline=time.monotonic()+100
    with subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,bufsize=0) as guest,selectors.DefaultSelector() as sel,uart.open('xb') as log:
        sel.register(guest.stdout,selectors.EVENT_READ)
        def wait(pattern):
            while time.monotonic()<deadline:
                if re.search(pattern,data,re.M):return
                if not sel.select(.3):continue
                block=os.read(guest.stdout.fileno(),8192)
                if not block:raise RuntimeError('guest exited')
                data.extend(block);log.write(block);log.flush()
                if b'Kernel panic' in data or len(data)>200000:raise ValueError('unexpected boot output')
            raise TimeoutError(pattern)
        try:
            wait(rb'^# $');cmd='cat /sys/devices/system/cpu/online; cat /proc/cpuinfo; sha256sum /bin/quad-check; /bin/quad-check; echo SMP_CODE_${?}_'+nonce+'\n'
            guest.stdin.write(cmd.encode());guest.stdin.flush();wait(rb'^SMP_CODE_[0-9]+_'+nonce.encode()+rb'\r?$')
            lines=data.decode(errors='replace').splitlines();text='\n'.join(lines)
            expected=['0-3' if n==4 else '0',digest(release/'quad-check.elf')+'  /bin/quad-check',f'SMP_CODE_{0 if n==4 else 2}_{nonce}']
            if not all(v in lines for v in expected) or lines.count(PASS)!=(2 if n==4 else 0) or lines.count('QUAD_SMP_FAILED')!=(0 if n==4 else 1):raise ValueError('SMP/affinity/hash/control evidence mismatch')
            if sorted(int(x) for x in re.findall(r'^processor\s*:\s*(\d+)\s*$',text,re.M))!=list(range(n)):raise ValueError('unexpected cpuinfo hart set')
            if not re.search(r'Platform HART Count\s*:\s*'+str(n)+r'\b',text) or 'LINUX_OSCHECK_PASS' not in text:raise ValueError('OpenSBI or OS probe mismatch')
        finally:
            guest.terminate()
            try:guest.wait(timeout=4)
            except subprocess.TimeoutExpired:guest.kill();guest.wait()
    return dict(harts=n,online=expected[0],probe_exit=0 if n==4 else 2,uart_sha256=digest(uart))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('release',type=Path);p.add_argument('out',type=Path);a=p.parse_args();a.out.mkdir();r=a.release.resolve()
    record=dict(scope='QEMU virt SMP Linux guest only; not Rocket RTL, board boot or throughput',firmware_sha256=digest(r/'fw_payload.bin'),probe_sha256=digest(r/'quad-check.elf'),runs=[run(n,r,a.out) for n in (4,1)])
    (a.out/'result.json').write_text(json.dumps(record,indent=2)+'\n');print('QEMU_FOUR_HART_GUEST_AND_ONE_HART_NEGATIVE_PASS')
