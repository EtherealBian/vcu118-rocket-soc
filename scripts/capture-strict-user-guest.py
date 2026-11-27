#!/usr/bin/env python3
"""Capture two user windows in a simulated Linux guest. The private dumps are not for publication."""
import argparse
from hashlib import sha256
import json
import os
import re
from pathlib import Path
import selectors
import socket
import subprocess
import time



def gdb_commands(d, port):
    return f'''set pagination off
set confirm off
set architecture riscv:rv64
set riscv use-compressed-breakpoints on
target remote 127.0.0.1:{port}
hbreak *0x106b0
python open({str(d/'armed')!r},'w').close()
continue
python
import gdb,json
p={str(d)!r}
r=lambda a:int(gdb.parse_and_eval(a)) & ((1<<64)-1)
rd=lambda a,n:bytes(gdb.selected_inferior().read_memory(a,n))
def snap(tag):
 regs=[r('$x%d'%i) for i in range(32)]; sp=regs[2]; pc=r('$pc'); rec=dict(pc=pc,regs=regs)
 for k in ['priv','satp','mstatus']:
  try: rec[k]=r('$'+k)
  except Exception: pass
 print('SNAP',tag,hex(pc),hex(sp),'s1=',hex(regs[9]),rec.get('priv'),flush=True)
 assert pc=={{'in':0x106b0,'out':0x10f3a}}[tag]
 # GCC keeps memblock[0] in s1 at the start fence.
 heap=regs[9] if tag=='in' else recin['regs'][9]
 areas=[('text',0x10158,0x1b000-0x10158),('rw',0x20f50,0xc30),('stack',sp-1536,1536+192),('heap',heap,2000)]
 for label,a,n in areas:
  b=rd(a,n);open(p+'/'+tag+'-'+label,'wb').write(b)
 rec['areas']=areas;open(p+'/'+tag+'.json','w').write(json.dumps(rec));return rec
recin=snap('in')
end
delete 1
hbreak *0x10f3a
continue
python snap('out')
delete 2
detach
quit
'''


def capture(d, port, command, env, elf):
    raw = bytearray()
    with subprocess.Popen(command, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                          stderr=subprocess.STDOUT, env=env) as vm, selectors.DefaultSelector() as sel:
        sel.register(vm.stdout, selectors.EVENT_READ)
        def wait(marker, sec=35):
            end = time.monotonic()+sec
            while time.monotonic() < end:
                if marker in raw:
                    return
                if sel.select(.15):
                    block = os.read(vm.stdout.fileno(), 8192)
                    if not block:
                        break
                    raw.extend(block)
            raise RuntimeError('guest did not reach the requested UART marker')

        def send(text):
            vm.stdin.write((text+'\n').encode()); vm.stdin.flush()

        try:
            wait(b'\n# ')
            send('echo 0 > /proc/sys/kernel/randomize_va_space; cat /proc/cmdline; '
                 'sha256sum /bin/coremark-g15-gc-lto-ooo-strict; echo GUEST_READY_$((2+2))')
            wait(b'\nGUEST_READY_4\r\n')
            if (sha256(elf.read_bytes()).hexdigest().encode()+b'  /bin/'+elf.stem.encode() not in raw or
                b'console=ttyS0,115200 no4lvl' not in raw):
                raise ValueError('running guest did not confirm the ELF and command line')
            for name,seed in [('performance','0x0'), ('validation','0x3415')]:
                sub = d/name; sub.mkdir(); script = sub/'cmds'
                script.write_text(gdb_commands(sub, port))
                with (sub/'gdb.txt').open('wb') as log, subprocess.Popen(
                        ['gdb-multiarch','-nx','-q','-batch',elf,'-x',script],
                        stdout=log, stderr=subprocess.STDOUT) as debugger:
                    try:
                        deadline = time.monotonic()+15
                        while time.monotonic()<deadline and not (sub/'armed').exists() and debugger.poll() is None:
                            time.sleep(.05)
                        if not (sub/'armed').exists(): raise RuntimeError('debugger did not arm the start fence')
                        send(f'/bin/{elf.stem} {seed} {seed} 0x66 4 7 1 2000; echo {name}_END_$?_$((2+2))')
                        if debugger.wait(timeout=25) != 0: raise RuntimeError('guest capture failed: '+name)
                    finally:
                        if debugger.poll() is None: debugger.kill()
                wait(f'\n{name}_END_0_4\r\n'.encode())
        finally:
            vm.terminate(); (d/'guest.uart').write_bytes(raw)
    crcs = re.findall(rb'^\[0\]crcfinal\s*:\s*(0x[0-9a-f]+)\s*$', bytes(raw), re.M)
    if crcs != [b'0x9f95',b'0x19d9']: raise ValueError('wrong guest CRC pair')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ['release', 'fw_jump', 'qemu_prefix', 'fresh_private_dir']:
        parser.add_argument(arg, type=Path)
    a = parser.parse_args()
    release, fw, q, D = (p.resolve() for p in (a.release,a.fw_jump,a.qemu_prefix,a.fresh_private_dir))
    D.mkdir(mode=0o700)
    elf = release/'coremark-g15-gc-lto-ooo-strict.elf'
    record = json.loads((Path(__file__).resolve().parents[1]/'docs/perf-mega175-linux-entry.json').read_bytes())
    for path, want in [(elf, record['inputs'][elf.name]), (release/'Image', record['inputs']['Image']),
                       (fw,'86d27b7b1d8aa7addf2238c96532ab7793ccb91c5f0188b93bdf83e7d9fc7b06'),
                       (q/'usr/bin/qemu-system-riscv64','05695049854d7850b30d707cf6dceab695166dd69118de8c74158ad4f3455a32')]:
        if sha256(path.read_bytes()).hexdigest()!=want: raise ValueError('wrong input: '+path.name)
    env = dict(os.environ,LD_LIBRARY_PATH=f'{q}/usr/lib/x86_64-linux-gnu:{q}/lib/x86_64-linux-gnu')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
    cmd=[q/'usr/bin/qemu-system-riscv64', '-M','virt', '-cpu','rv64gcsu-v1.10.0', '-smp','1',
         '-m','256M', '-nographic', '-monitor','none', '-bios',fw, '-kernel',release/'Image',
         '-append','console=ttyS0,115200 no4lvl', '-gdb',f'tcp:127.0.0.1:{port}']
    capture(D, port, cmd, env, elf)
    print('CAPTURED_TWO_LINUX_GUEST_WINDOWS_NOT_A_BOARD_SCORE')
