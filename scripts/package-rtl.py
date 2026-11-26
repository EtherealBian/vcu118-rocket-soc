#!/usr/bin/env python3
"""Portable reproduction kit for exactly the elaborated board RTL (no Vivado install/IP output)."""
import argparse,hashlib,os,re,tempfile,zipfile
from pathlib import Path as P
from collections import OrderedDict
root=P(__file__).resolve().parents[1]; cy=root/'third_party/chipyard'; shell=cy/'fpga/fpga-shells'; fp=cy/'fpga'
ap=argparse.ArgumentParser();ap.add_argument('--out',type=P);ap.add_argument('--config',choices=['RocketVCU118Config','Dot4RocketVCU118Config'],default='RocketVCU118Config');args=ap.parse_args(); members={}
if args.out is None:
 if args.config!='RocketVCU118Config':ap.error('an explicit fresh --out is required for the accelerator variant')
 args.out=root/'artifacts/vcu118-generated-rtl.zip'
if args.config!='RocketVCU118Config' and args.out.exists():ap.error('variant output exists')
cfg='chipyard.fpga.vcu118.VCU118FPGATestHarness.'+args.config; gen=fp/'generated-src'/cfg
def put(k,b):
 if isinstance(b,P):b=b.read_bytes()
 if isinstance(b,str):b=b.encode()
 if k in members and members[k]!=b:raise ValueError('filename collision '+k)
 members[k]=b
names=[]
for line in (gen/(cfg+'.vsrcs.f')).read_text().splitlines():
 if not line.strip():continue
 if '/third_party/chipyard/' in line:
  p=(cy/line.split('/third_party/chipyard/',1)[1]).resolve()
  if cy.resolve() not in p.parents:raise ValueError('source escapes pinned checkout')
 elif args.config=='Dot4RocketVCU118Config' and line.replace('\\','/').endswith('/rtl/accel/dot4_i8.sv'):
  if line not in [str(root/'rtl/accel/dot4_i8.sv'),'/mnt/c/risc_v/rtl/accel/dot4_i8.sv']:raise ValueError('unknown external source '+line)
  p=root/'rtl/accel/dot4_i8.sv'
 else:raise ValueError('source outside pinned checkout: '+line)
 if not p.is_file():raise FileNotFoundError(p)
 k='rtl/'+p.name;put(k,p);names.append(k)
assert len(set(names))>300
put('sources.f','\n'.join(dict.fromkeys(names))+'\n');
for ext in ['shell.vivado.tcl','shell.sdc','shell.xdc','vcu118mig.vivado.tcl','harnessSysPLL.vivado.tcl','dts','memmap.json','l2.json']:
 put('board/'+cfg+'.'+ext,gen/(cfg+'.'+ext))
for folder in ['xilinx/common/tcl','xilinx/vcu118']:
 for f in (shell/folder).rglob('*'):
  if f.is_file():put('shell/'+f.relative_to(shell).as_posix(),f)
for f in ((fp/'src/main/resources/vcu118/sdboot/build').glob('sdboot.*')):
 if f.suffix in ('.elf','.bin'):put('rom/'+f.name,f)
for source,label in [(cy,'chipyard'),(shell,'fpga-shells'),(cy/'generators/rocket-chip','rocket-chip'),(cy/'generators/rocket-chip-blocks','rocket-chip-blocks'),(cy/'generators/testchipip','testchipip'),(cy/'generators/rocket-chip-inclusive-cache','rocket-chip-inclusive-cache'),(cy/'generators/diplomacy','diplomacy')]:
 for f in source.glob('LICENSE*'):
  if f.is_file():put('notices/'+label+'/'+f.name,f)
put('THIRD-PARTY.md',root/'THIRD-PARTY.md');put('implement.tcl',root/'scripts/implement.tcl');put('build.tcl','''# Run from a new, short path without spaces (e.g., C:/vcu118kit). Never overwrite a prior run.
set here [file dirname [file normalize [info script]]];if {[regexp {\\s} $here]} {error "extract to path without spaces"}
set argv [list [file join $here sources.f] [file join $here shell xilinx common tcl] [file join $here run-[clock seconds]]];set argc 3
source [file join $here implement.tcl]
''');put('README.txt', '''VCU118 Rocket baseline, generated files from Chipyard 1.13.0, Vivado 2024.2. Extract to an empty short path without spaces. In that path run: vivado -mode batch -source build.tcl\nThe file list and the embedded ROM are the actual generated board design; generated AMD IP must be recreated using a licensed installation. This package is neither a verified board boot nor a timing waiver. RTL_ROOT_SHA256.txt authenticates content not origin. Do not unpack different versions in the same folder.\n''');
if args.config=='Dot4RocketVCU118Config':
 if members.get('rtl/dot4_i8.sv')!=(root/'rtl/accel/dot4_i8.sv').read_bytes():raise ValueError('generator did not preserve the verified accelerator HDL')
 if b'vcu118lab,dot4-i8-v1' not in members['board/'+cfg+'.dts']:raise ValueError('missing accelerator in device tree')
 put('overlay/Dot4Rocket.scala',root/'rtl/accel/chipyard/Dot4Rocket.scala');members['README.txt']+=b'Optional Dot4RocketVCU118Config: MMIO at 0x64002000. This archive initially retains the stock board ROM.\n'
dig=lambda b:hashlib.sha256(b).hexdigest();manifest=''.join(dig(b)+'  '+k+'\n' for k,b in sorted(members.items()));put('RTL_ROOT_SHA256.txt',manifest)
fd,tmp=tempfile.mkstemp(suffix='.part',dir=args.out.parent);os.close(fd)
try:
 with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5)as z:
  for k,b in sorted(members.items()):
   i=zipfile.ZipInfo(k,(2024,12,1,0,0,0));i.compress_type=zipfile.ZIP_DEFLATED;z.writestr(i,b)
 with zipfile.ZipFile(tmp)as z:
  assert z.testzip() is None
  for k,b in members.items():assert z.read(k)==b,k
 os.replace(tmp,args.out);print('RTL_PACKAGE_VERIFIED sources='+str(len(set(names)))+' members='+str(len(members))+' bytes='+str(args.out.stat().st_size)+' sha256='+dig(args.out.read_bytes()))
finally:
 if os.path.exists(tmp):os.unlink(tmp)
