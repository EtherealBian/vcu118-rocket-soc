#!/usr/bin/env python3
"""Boot the same firmware payload on QEMU virt; this does not emulate the VCU118."""
import re, os, pathlib, selectors, subprocess, sys, time, shutil
root=pathlib.Path(__file__).resolve().parents[1]; tools=pathlib.Path(os.environ.get('VCU_TOOLS',pathlib.Path.home()/'.local/share/vcu118-tools')); q=tools/'qemu'; env=dict(os.environ); env['LD_LIBRARY_PATH']=f'{q}/usr/lib/x86_64-linux-gnu:{q}/lib/x86_64-linux-gnu:'+env.get('LD_LIBRARY_PATH',''); exe=q/'usr/bin/qemu-system-riscv64'; bios=pathlib.Path(os.environ.get('VCU_FIRMWARE',root/'artifacts/fw_payload.bin')); assert bios.is_file()
if sys.argv[1:] not in ([], ['--oscheck']): raise SystemExit('usage: qemu-smoke.py [--oscheck]')
want_oscheck = bool(sys.argv[1:]); os_marker=b'LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d'
args=[str(exe) if exe.is_file() else 'qemu-system-riscv64','-machine','virt','-smp','1','-m','256M','-nographic','-monitor','none','-bios',str(bios)]
with (root/'logs'/os.environ.get('VCU_QEMU_LOG','qemu-uart.txt')).open('wb') as log, subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,bufsize=0) as proc:
 try:
  sel=selectors.DefaultSelector(); sel.register(proc.stdout,selectors.EVENT_READ); data=b''; challenge=False; end=time.monotonic()+120
  while time.monotonic()<end:
   if not sel.select(1): continue
   block=os.read(proc.stdout.fileno(),8192)
   if not block: break
   log.write(block);log.flush();data=(data+block)[-200000:]
   if b'Kernel panic' in data or b'LINUX_OSCHECK_FAILED' in data: break
   if not challenge and b'VCU118_INITRAMFS_READY' in data and b'SOC_CHECK_PASS bytes=16777216' in data and (not want_oscheck or re.search(rb'^'+os_marker+rb'\r?\n',data,re.M)):
    proc.stdin.write(b'echo QEMU_SHELL_$((40+2))\n'); proc.stdin.flush(); challenge=True
   if challenge and re.search(rb'(?:^|\n)(?:# )?QEMU_SHELL_42\r?\n',data):
    print('QEMU_VIRT_SHELL_PASS: same fw_payload.bin, 16 MiB user memory, integer/FP check, shell challenge'+('; two-process OS workload verified' if want_oscheck else '')); sys.exit(0)
  raise SystemExit('QEMU smoke failed or timed out; see logs/qemu-uart.txt')
 finally:
  proc.terminate()
  try: proc.wait(timeout=4)
  except subprocess.TimeoutExpired: proc.kill(); proc.wait()
