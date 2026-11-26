#!/usr/bin/env python3
"""Check the *generated* board device-tree and the linked ROM's handoff ABI in WSL."""
import argparse, hashlib, pathlib, re, subprocess, tempfile
P=pathlib.Path; ap=argparse.ArgumentParser();ap.add_argument('dts',type=P);ap.add_argument('--rom',type=P,required=True,help='sdboot.elf whose adjacent .bin was used for elaboration'); args=ap.parse_args()
def need(ok,msg):
 if not ok: raise SystemExit('DT_CONTRACT_FAIL: '+msg)
with tempfile.TemporaryDirectory() as td:
 dtb=P(td)/'board.dtb'; subprocess.run(['dtc','-q','-I','dts','-O','dtb','-o',str(dtb),str(args.dts)],check=True)
 def fd(*argv):return subprocess.check_output(['fdtget',*map(str,argv)],text=True).strip()
 def st(n,k):return fd('-t','s',dtb,n,k)
 def cells(n,k):return [int(x,16) for x in fd('-t','x',dtb,n,k).split()]
 def walk(p):
  yield p
  for n in fd('-l',dtb,p).splitlines():yield from walk(p.rstrip('/')+'/'+n)
 nodes=list(walk('/')); properties={p:set(fd('-p',dtb,p).splitlines())for p in nodes}
 def uniq(xs,desc):need(len(xs)==1,desc+': '+str(xs));return xs[0]
 def kind(val):return [p for p in nodes if 'device_type' in properties[p] and st(p,'device_type')==val]
 def compat(val):return uniq([p for p in nodes if 'compatible' in properties[p] and val in st(p,'compatible').split()],val)
 def integer(vals):
  ret=0
  for x in vals:ret=(ret<<32)|x
  return ret
 def reg(p):
  parent=p.rsplit('/',1)[0] or '/'; vals=cells(p,'reg'); ac=cells(parent,'#address-cells')[0]; sc=cells(parent,'#size-cells')[0]; need(len(vals)>=ac+sc,'bad reg: '+p); return integer(vals[:ac]),integer(vals[ac:ac+sc])
 cpu=uniq(kind('cpu'),'expected one hart'); isa=st(cpu,'riscv,isa');need(isa.startswith('rv64') and set('imafdc')<=set(isa.split('_')[0][4:]),isa); need(st(cpu,'mmu-type')=='riscv,sv39','Sv39'); rate=cells('/cpus','timebase-frequency')[0];need(cells(cpu,'timebase-frequency')==[rate],'cpu timebase differs'); gd=args.dts.parent/'gen-collateral'; rtc=(gd/'DigitalTop.sv').read_text(); m=re.search(r"int_rtc_tick = int_rtc_tick_c_value == \d+'h([0-9a-f]+);",rtc,re.I);need(m is not None and '.tick' in rtc and 'int_rtc_tick ?' in rtc,'unrecognized RTC divider');div=int(m[1],16)+1; need(rate==100000 and rate*div==100000000,'RTC clock/divider mismatch');print('RTC',rate,'Hz; generated terminal count',div-1)
 mem=uniq([p for p in kind('memory') if 'status' not in properties[p] or st(p,'status') in ('okay','ok')],'enabled memory region'); need(reg(mem)==(0x80000000,0x80000000),'2 GiB DDR');print('CPU',isa,'DDR',reg(mem))
 handles={cells(p,'phandle')[0]:p for p in nodes if 'phandle' in properties[p]}
 for name,start in [('sifive,uart0',0x64000000),('sifive,spi0',0x64001000)]:
  p=compat(name); need(reg(p)[0]==start,'reg '+p);need('interrupts' in properties[p] or 'interrupts-extended' in properties[p],'irq '+p); cp=handles[cells(p,'clocks')[0]]; need(cells(cp,'clock-frequency')==[100000000],'peripheral clock '+p); print(name,p,cp,'100 MHz')
 slot=compat('mmc-spi-slot');need(slot.rsplit('/',1)[0]==compat('sifive,spi0') and cells(slot,'reg')==[0],'SPI slot/CS');need(reg(compat('riscv,clint0'))[0]==0x02000000,'CLINT');need(reg(compat('riscv,plic0'))[0]==0x0c000000,'PLIC')
 need(st('/chosen','stdout-path')==compat('sifive,uart0'),'serial stdout selection');need(st('/aliases','serial0')==compat('sifive,uart0'),'serial0 alias');
 sym=subprocess.check_output(['nm','-n',str(args.rom)],text=True); addr=int(re.search(r'^([0-9a-fA-F]+)\s+\w\s+dtb$',sym,re.M)[1],16); rom=args.rom.with_suffix('.bin').stat().st_size;need(0x10000+rom==addr,'x11 must point to appended DTB');need(rom+dtb.stat().st_size<=0x10000,'ROM overflow');words=re.search(r"wire \[1023:0\]\[63:0\] _GEN =\s*'\{(.*?)\};",(gd/'TLROM.sv').read_text(),re.S);need(words is not None,'unknown ROM expression'); vals=re.findall(r"64'h([0-9A-Fa-f]+)",words[1]);need(len(vals)==1024,'ROM word count'); raw=b''.join(int(v,16).to_bytes(8,'little') for v in reversed(vals));expected=args.rom.with_suffix('.bin').read_bytes()+dtb.read_bytes();need(raw[:len(expected)]==expected and not any(raw[len(expected):]),'hardware ROM does not contain this image+DTB+zero padding');print('MATCHED_GENERATED_ROM_RTL bytes',len(expected),'sha256',hashlib.sha256(expected).hexdigest());print('GENERATED_BOARD_DT_CONTRACT_PASS',hex(addr),'dtb_bytes='+str(dtb.stat().st_size),'(no board access)')
