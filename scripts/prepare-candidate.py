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
 def replace(path,old,new):
  t=path.read_text();assert t.count(old)==1,(path,old);path.write_text(t.replace(old,new))
 # Exact byte checks prevent silent drift in the semantics of the pinned generated source.
 top=get('rtl/VCU118FPGATestHarness.sv');xdc,=get('board').glob('*.shell.xdc');assert h(top.read_bytes())=='472603ea4787b55f4b0794aaac56cf93e7e7ab48aba8b80360458532590bd55a';assert h(xdc.read_bytes())=='6be4770f253df7036cd192b0bc5273e47a08c66852081625d9cd12215ee2f8fa'
 replace(top,'  ChipTop chiptop0 (','''  // RX has no source clock. Give only the synchronizer first stage the asynchronous pin.
  (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg uart_rx_meta = 1'b1, uart_rx_sync = 1'b1;
  always @(posedge _dutWrangler_auto_out_0_clock) begin
    uart_rx_meta <= _io_uart_bbIn_rxd_a2b_b;
    uart_rx_sync <= uart_rx_meta;
  end
  ChipTop chiptop0 (''');replace(top,'.uart_0_rxd                (_io_uart_bbIn_rxd_a2b_b)', '.uart_0_rxd                (uart_rx_sync)')
 unused={'uart_ctsn','uart_rtsn','sdio_spi_dat_1','sdio_spi_dat_2','jtag_srst_n'};clocked={'jtag_jtag_TCK','jtag_jtag_TMS','jtag_jtag_TDI'};outputs={'uart_txd','sdio_spi_cs','sdio_spi_dat_3','jtag_jtag_TDO'};seen=set();lines=[]
 for l in xdc.read_text().splitlines():
  if not l.startswith('set_property IOB '):lines.append(l);continue
  p=re.search(r'get_ports \{(\w+)\}',l)[1];seen.add(p)
  if p in outputs:lines.append(l)
  elif p=='sdio_spi_dat_0':lines.append('set_property IOB TRUE [get_cells {io_spi_bbIn_dq_1_i_REG_reg}]')
  elif p in unused|clocked|{'uart_rxd'}:lines.append('# IOB removed for '+p+': '+('unused in this configuration' if p in unused else ('use paired fabric ASYNC_REG stages' if p=='uart_rxd' else 'clock or multiple synchronous TAP endpoints')))
  else:raise ValueError('unknown IOB role '+p)
 assert seen==unused|clocked|outputs|{'uart_rxd','sdio_spi_dat_0'};xdc.write_text('\n'.join(lines)+'\n')
 # init.tcl already registered the IPs; do not re-read them into the same project.
 synth=get('shell/xilinx/common/tcl/synth.tcl');replace(synth,'read_ip [glob -directory $ipdir [file join * {*.xci}]]','''foreach xci [glob -directory $ipdir [file join * {*.xci}]] {
  if {![llength [get_files -quiet [file normalize $xci]]]} {read_ip $xci}
}''')
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
