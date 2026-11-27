#!/usr/bin/env python3
"""Derive candidate boot-ROM/synchronized-UART kit from a verified stock RTL zip, without editing Chipyard. Run in WSL (nm/dtc required)."""
from pathlib import Path as P,PurePosixPath
from zipfile import ZipFile
from hashlib import sha256
import argparse,re,subprocess,sys,struct,tempfile

def apply(stock,romdir,out,boot="gpt",irq_sync=False,irq_front_end=False):
 if irq_front_end and not irq_sync: raise ValueError("--irq-front-end requires --irq-sync")
 label={"gpt":"ROM4 SDHC primary GPT/checksum boot", "uart5":"ROM5 UART-only framed recovery boot (no SD access)"}[boot]
 h=lambda b:sha256(b).hexdigest(); get=lambda k:out/k
 if out.exists():raise ValueError('fresh candidate output directory required')
 with ZipFile(stock) as z:
  sums={k:v for v,k in (l.split('  ',1) for l in z.read('RTL_ROOT_SHA256.txt').decode().splitlines())}
  if set(z.namelist())!={*sums,'RTL_ROOT_SHA256.txt'} or z.testzip():raise ValueError('invalid stock archive')
  for k,v in sums.items():
   pp=PurePosixPath(k)
   if pp.is_absolute() or '..' in pp.parts or ':' in k or '\\' in k or h(z.read(k))!=v:raise ValueError('unsafe or corrupt input '+k)
  out.mkdir();
  for k in sums:
   path=get(k);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(z.read(k))
 import runpy
 physical=runpy.run_path(str(P(__file__).with_name('board_shell_overlay.py')))
 xdc,=get('board').glob('*.shell.xdc')
 shell_files=(get('rtl/VCU118FPGATestHarness.sv'),xdc,get('shell/xilinx/common/tcl/synth.tcl'))
 for path,data in zip(shell_files,physical['transform'](*(p.read_bytes() for p in shell_files))):path.write_bytes(data)
 dts,=get('board').glob('*.dts');dtb=subprocess.check_output(['dtc','-q','-I','dts','-O','dtb',str(dts)]);tl=get('rtl/TLROM.sv');sv=tl.read_text();m=re.search(r"(wire \[1023:0\]\[63:0\] _GEN =\s*'\{)(.*?)(\};)",sv,re.S);assert m;old=b''.join(int(v,16).to_bytes(8,'little') for v in reversed(re.findall("64'h([0-9a-fA-F]+)",m[2])));stock_bytes=get('rom/sdboot.bin').read_bytes()+dtb;assert old==stock_bytes.ljust(8192,b'\0');newrom=(romdir/'sdboot.bin').read_bytes();assert (b'UART5_READY v1' if boot=='uart5' else b'ROM4_INIT') in newrom,'boot variant mismatch';sym=subprocess.check_output(['nm','-n',str(romdir/'sdboot.elf')],text=True);addr=int(re.search(r'^([0-9a-f]+)\s+\w\s+dtb$',sym,re.M)[1],16);assert addr==0x10000+len(newrom);body=newrom+dtb;assert len(body)<=len(old);words=struct.unpack('<1024Q',body.ljust(8192,b'\0'));expr=',\n    '.join(f"64'h{x:016x}" for x in reversed(words));tl.write_text(sv[:m.start(2)]+'\n    '+expr+sv[m.end(2):]);get('rom/sdboot.bin').write_bytes(newrom);get('rom/sdboot.elf').write_bytes((romdir/'sdboot.elf').read_bytes());get('rom/board.dtb').write_bytes(dtb)
 if irq_sync:
  # No logic/latency changes; only the pinned unreset three-stage synchronizer is marked.
  import runpy
  overlay=runpy.run_path(str(P(__file__).with_name('annotate-irq-sync.py')))
  leaf=get('rtl/'+overlay['NAME']); leaf.write_bytes(overlay['annotated'](leaf.read_bytes()))
  label += '; IRQ synchronizer ASYNC_REG and SRL extraction disabled (check integrated netlist)'
 if irq_front_end:
  overlay=runpy.run_path(str(P(__file__).with_name('prepare-halt-merge.py')))
  overlay['install'](out); label += '; independently registered halt request levels (+2 debug clock edges)'
 get('README.txt').write_text(f'VCU118 candidate: {label} and two-flop UART receive synchronizer. No authentication; no board signoff. Rebuild: vivado -mode batch -source build.tcl. See project README.\n');get('CANDIDATE.sha256').write_text(''.join(h(p.read_bytes())+'  '+p.relative_to(out).as_posix()+'\n' for p in sorted(out.rglob('*')) if p.is_file()));print('CANDIDATE_PREPARED',out,'firmware_bytes',len(newrom),'dtb',hex(addr),'rom_with_dtb_sha256',h(body),'stock_zip_sha256',h(stock.read_bytes()))
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 for name in ('stock','romdir','out'):parser.add_argument(name,type=P)
 parser.add_argument('--irq-front-end',action='store_true',help='buffered ungated kit only: synchronize halt before OR; adds two cycles')
 parser.add_argument('--irq-sync',action='store_true',help='mark the exact pinned IRQ synchronizer leaf; independent variant');parser.add_argument('--boot',choices=('gpt','uart5'),default='gpt');apply(**vars(parser.parse_args()))
