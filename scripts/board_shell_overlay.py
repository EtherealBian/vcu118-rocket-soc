#!/usr/bin/env python3
"""Apply only the pinned physical RX/XDC and duplicate-IP import fixes, never the ROM."""
from hashlib import sha256
import re

# Stock and corrected bytes, independent of the processor and UART divisor.
PINS = (
 ('472603ea4787b55f4b0794aaac56cf93e7e7ab48aba8b80360458532590bd55a','31646f1a0ff1f85d94474108f4f21895969400cb83ffab8f5a7e93351c062823'),
 ('6be4770f253df7036cd192b0bc5273e47a08c66852081625d9cd12215ee2f8fa','3cee5e270b2fe3cdeb9fa5ba95d44192a4ead4a24b3ff5c352afdff1ec7eaa96'),
 ('18c0ca6057fdb3e7b175a3c0558b228b2cc106fb8b278ae9fab5da628bb30c80','c9d755bf1bb8e6352cf1884eaf2895420f9000311510671dd1a7eb7c008f36d1'),
)

def replace(text, old, new):
 if text.count(old)!=1: raise ValueError('missing or ambiguous shell binding')
 return text.replace(old,new)

def transform(top,xdc,synth):
 inputs=(top,xdc,synth)
 if tuple(sha256(b).hexdigest() for b in inputs)!=tuple(p[0] for p in PINS): raise ValueError('unreviewed physical shell')
 top,xdc,synth=(b.decode() for b in inputs)
 top=replace(top,'  ChipTop chiptop0 (','''  // RX has no source clock. Give only the synchronizer first stage the asynchronous pin.
  (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg uart_rx_meta = 1'b1, uart_rx_sync = 1'b1;
  always @(posedge _dutWrangler_auto_out_0_clock) begin
    uart_rx_meta <= _io_uart_bbIn_rxd_a2b_b;
    uart_rx_sync <= uart_rx_meta;
  end
  ChipTop chiptop0 (''');top=replace(top,'.uart_0_rxd                (_io_uart_bbIn_rxd_a2b_b)', '.uart_0_rxd                (uart_rx_sync)')
 unused={'uart_ctsn','uart_rtsn','sdio_spi_dat_1','sdio_spi_dat_2','jtag_srst_n'};clocked={'jtag_jtag_TCK','jtag_jtag_TMS','jtag_jtag_TDI'};outputs={'uart_txd','sdio_spi_cs','sdio_spi_dat_3','jtag_jtag_TDO'};seen=set();lines=[]
 for l in xdc.splitlines():
  if not l.startswith('set_property IOB '):lines.append(l);continue
  p=re.search(r'get_ports \{(\w+)\}',l)[1];seen.add(p)
  if p in outputs:lines.append(l)
  elif p=='sdio_spi_dat_0':lines.append('set_property IOB TRUE [get_cells {io_spi_bbIn_dq_1_i_REG_reg}]')
  elif p in unused|clocked|{'uart_rxd'}:lines.append('# IOB removed for '+p+': '+('unused in this configuration' if p in unused else ('use paired fabric ASYNC_REG stages' if p=='uart_rxd' else 'clock or multiple synchronous TAP endpoints')))
  else:raise ValueError('unknown IOB role '+p)
 if seen!=unused|clocked|outputs|{'uart_rxd','sdio_spi_dat_0'}: raise ValueError('unexpected IOB set')
 xdc='\n'.join(lines)+'\n'
 synth=replace(synth,'read_ip [glob -directory $ipdir [file join * {*.xci}]]','''foreach xci [glob -directory $ipdir [file join * {*.xci}]] {
  if {![llength [get_files -quiet [file normalize $xci]]]} {read_ip $xci}
}''')
 outputs=tuple(v.encode() for v in (top,xdc,synth))
 if tuple(sha256(b).hexdigest() for b in outputs)!=tuple(p[1] for p in PINS): raise ValueError('unexpected physical shell delta')
 return outputs
