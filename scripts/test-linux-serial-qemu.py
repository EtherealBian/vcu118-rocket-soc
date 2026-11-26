#!/usr/bin/env python3
"""Exercise the real BusyBox command and interactive line pacing on QEMU virt; no board claims."""
import argparse,importlib.util,os,re,secrets,selectors,subprocess,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('lsr',Path(__file__).with_name('review-linux-serial.py'));lsr=importlib.util.module_from_spec(spec);spec.loader.exec_module(lsr)
p=argparse.ArgumentParser(description=__doc__);p.add_argument('firmware',type=Path);p.add_argument('out',type=Path);a=p.parse_args();a.out.mkdir()
q=Path(os.getenv('VCU_TOOLS',Path.home()/'.local/share/vcu118-tools'))/'qemu';env=dict(os.environ);env['LD_LIBRARY_PATH']=f'{q}/usr/lib/x86_64-linux-gnu:{q}/lib/x86_64-linux-gnu:'+env.get('LD_LIBRARY_PATH','')
n=secrets.token_hex(7);v=[secrets.token_hex(128) for _ in range(32)];raw=bytearray();stop=time.monotonic()+90
with subprocess.Popen([q/'usr/bin/qemu-system-riscv64','-machine','virt','-m','256M','-smp','1','-nographic','-monitor','none','-bios',a.firmware.resolve()],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=0,env=env) as proc,selectors.DefaultSelector() as sel:
    sel.register(proc.stdout,selectors.EVENT_READ)
    def wait(pattern):
        while time.monotonic()<stop:
            if re.search(pattern,raw,re.M):return
            if not sel.select(.2):continue
            b=os.read(proc.stdout.fileno(),8192)
            if not b:break
            raw.extend(b)
        raise TimeoutError(str(pattern))
    def send(line):proc.stdin.write((line+'\n').encode());proc.stdin.flush()
    try:
        wait(rb'^# $');send('echo LINK_LIVE_$((7*6))_'+n);wait(rb'^(?:# )?LINK_LIVE_42_'+n.encode()+rb'\r?\n');send(lsr.command(n));wait(rb'^LINK_READY_'+n.encode()+rb'\r?\n')
        for i,line in enumerate(v,1):
            send(line);wait(f'^LINK_ACK_{i}_{n}\\r?\\n'.encode())
        wait(rb'^LINK_END_42_'+n.encode()+rb'\r?\n');lsr.exchange(bytes(raw),v,n)
    finally:
        proc.terminate();proc.wait(timeout=5);(a.out/'uart.txt').write_bytes(bytes(raw));(a.out/'vectors.txt').write_text('\n'.join(v)+'\n');(a.out/'nonce.txt').write_text(n)
(a.out/'test.ok').write_text('QEMU shell: 32 independent line digests; no VCU118 PLIC claim\n');print('QEMU_LINUX_SERIAL_SHA256_EXCHANGE_PASS records=32')
