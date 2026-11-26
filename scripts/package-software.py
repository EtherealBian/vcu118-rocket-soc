#!/usr/bin/env python3
"""Package reviewable baseline scripts, images & chosen evidence. No board bit, Git cache or tools."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED,ZipInfo
from hashlib import sha256
import tempfile,os
root=Path(__file__).resolve().parents[1]; aud=root/'artifacts'; entries={}
def add(rel):
 p=root/rel
 if not p.is_file():raise FileNotFoundError(str(p))
 entries[p.relative_to(root).as_posix()]=p
for name in ['README.md','THIRD-PARTY.md','VCU118-SOC-v0.1.md','sources.sha256','artifacts/fw_payload.bin','artifacts/vcu118-linux.img','artifacts/vcu118-linux-data.img','artifacts/Image','artifacts/kernel.config','artifacts/soc-check.elf','artifacts/software.sha256']:
 add(name)
for d in ['scripts','software','tests','rtl','artifacts/bare','artifacts/rom100']:
 for p in (root/d).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts: add(p)
for name in ['board-dt-v2.txt','fdt-relocation-v3.txt','data-v3-repro-check.txt','rtl-package-stock-r2.txt','verilator-setup-fixed.txt','rtl-boot-b.txt','rtl-debug-bare-c.txt','release-check-v3.txt','repro-v3.txt','storage-v3.txt','rom-elaboration-toolchain.txt','accel-hold-console-v2.txt','bare-build.txt','rom-build.txt','bare-gpt.txt','linux-v3-gpt.txt','qemu-v3-a-uart.txt','qemu-v3-a.txt','host-selftest.txt','test-sd.txt','generator-sources.txt','accel-sim-v2.txt','ddr-preflight.txt','board-probe.txt']:
 add('logs/'+name)
candidates=sorted((root/'logs').glob('qemu-repeated.*/result.txt'),key=lambda p:p.stat().st_mtime,reverse=True)
firm=sha256((aud/'fw_payload.bin').read_bytes()).hexdigest()
completed=next((p for p in candidates if (p.parent/'firmware.sha256').read_text().split()[0]==firm and 'QEMU_VIRT_REPEATED_PASS runs=10 ' in p.read_text()),None)
if not completed:raise ValueError('no passing 10-boot run for published firmware')
for p in completed.parent.iterdir():add(p)
# The storage test reboots a temporary copy of this exact release.
report=(root/'logs/storage-v3.txt').read_text(); import re
storename=re.search(r'QEMU_STORAGE_PASS[^\n]*?/logs/(qemu-storage\.[A-Za-z0-9_-]+)',report).group(1)
for i in (1,2):add(f'logs/{storename}/uart-{i}.txt')
if sha256((aud/'vcu118-linux-data.img').read_bytes()).hexdigest() not in report:raise ValueError('storage image does not match test')
fd,tmp=tempfile.mkstemp(prefix='software-kit-',suffix='.part',dir=str(aud)); os.close(fd);tmp=Path(tmp)
try:
 with ZipFile(tmp,'w',compression=ZIP_DEFLATED,compresslevel=4) as z:
  def write(k,data):
   item=ZipInfo(k,(2024,12,1,0,0,0));item.compress_type=ZIP_DEFLATED;item.create_system=3;item.external_attr=0o100644<<16;z.writestr(item,data,compresslevel=4)
  inventory=[]
  for k,p in sorted(entries.items()):
   data=p.read_bytes(); inventory.append(sha256(data).hexdigest()+'  '+k);write(k,data)
  write('CONTENTS.sha256','\n'.join(inventory)+'\n')
 with ZipFile(tmp) as z:
  if z.testzip() is not None:raise ValueError('zip CRC')
  for row in z.read('CONTENTS.sha256').decode().splitlines():
   digest,k=row.split('  ',1)
   if sha256(z.read(k)).hexdigest()!=digest:raise ValueError(k)
 dest=aud/'vcu118-software-kit.zip';os.replace(tmp,dest);print('SOFTWARE_KIT_VERIFIED',dest,'files',len(entries),'bytes',dest.stat().st_size,'sha256',sha256(dest.read_bytes()).hexdigest())
finally:
 if tmp.exists():tmp.unlink()
