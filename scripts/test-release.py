#!/usr/bin/env python3
"""Check the bytes actually shipped, independent of the image packer and ELF builder."""
from pathlib import Path
import hashlib,struct
r=Path(__file__).resolve().parents[1]/'artifacts'; fw=(r/'fw_payload.bin').read_bytes(); k=(r/'Image').read_bytes(); rom=(r/'rom100/sdboot.elf').read_bytes(); bare=(r/'bare/bringup.elf').read_bytes()
def require(v,msg):
 if not v: raise SystemExit('FAIL: '+msg)
for elf,entry in [(bare,0x80000000),(rom,0x10000)]:
 require(elf[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',elf,18)[0]==243 and struct.unpack_from('<Q',elf,24)[0]==entry,'bad RV64 little-endian ELF entry')
require(k[56:60]==b'RSC\x05' and 0<len(fw)<=30<<20 and fw[0x200000:0x200000+len(k)]==k,'Linux payload/offset mismatch')
for name,data in [('vcu118-linux.img',fw),('bare/bringup-vcu118.img',(r/'bare/bringup.bin').read_bytes())]:
 with (r/name).open('rb') as f:
  f.seek(34*512); require(f.read(len(data))==data,name+' payload does not match'); require(not any(f.read((30<<20)-len(data))),name+' stale bytes in boot ROM load window')
 print(name, 'payload_bytes='+str(len(data)), 'sha256='+hashlib.sha256((r/name).read_bytes()).hexdigest())
for row in (r/'software.sha256').read_text().splitlines():
 h,n=row.split('  '); require(hashlib.sha256((r/n).read_bytes()).hexdigest()==h,'stale hash '+n)
print('RELEASE_LAYOUT_PASS (no board access)')
