#!/usr/bin/env python3
"""Prepare four standalone VCU118 register-file implementation fixtures, no Vivado invocation.

Wrap the real BOOM register-read/write parent (including bypass) with timing
boundary registers, not a simplified replacement. The two roles of each width
must get byte-identical wrappers, constraints and parent modules.
"""
import argparse
import json
from pathlib import Path
import re
import runpy
import shutil

HERE=Path(__file__).resolve().parent
KIT=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))
RF=runpy.run_path(str(HERE/'check-mega-regfile.py'))
XDC='''# Standalone timing boundary, NOT the PLL or any board I/O specification.
create_clock -name rf_clk -period 5.714 [get_ports clock]
set_property HD.CLK_SRC BUFGCE_X0Y218 [get_ports clock]
set_input_delay -clock [get_clocks rf_clk] 0.000 [get_ports {raddr[*] wen[*] waddr[*] wdata[*]}]
set_output_delay -clock [get_clocks rf_clk] 0.000 [get_ports {rdata[*]}]
'''


def wrapper(bits,readers,writers,parent,text):
    clean=re.sub(r'//[^\n]*','',text)
    match,=re.findall(r'\bmodule\s+'+parent+r'\s*\((.*?)\)\s*;',clean,re.S)
    ports={}
    for token in match.split(','):
        m=re.fullmatch(r'\s*(input|output)\s*(?:\[(\d+):0\])?\s*(\w+)\s*',token)
        if not m or m[3] in ports:raise ValueError('ambiguous parent port')
        ports[m[3]]=(m[1],1+int(m[2] or 0))
    expected={}; conns=[]
    def pin(direction,name,width,signal):
        expected[name]=(direction,width);conns.append(f'.{name}({signal})')
    pin('input','clock',1,'clock');pin('input','reset',1,"1'b0")  # no reset on stored data or boundary FFs
    for i in range(readers):
        pin('input',f'io_read_ports_{i}_addr',7,f'ra_q[{7*i} +: 7]')
        pin('output',f'io_read_ports_{i}_data',bits,f'rd[{bits*i} +: {bits}]')
    for i in range(writers):
        pin('input',f'io_write_ports_{i}_valid',1,f'we_q[{i}]')
        pin('input',f'io_write_ports_{i}_bits_addr',7,f'wa_q[{7*i} +: 7]')
        pin('input',f'io_write_ports_{i}_bits_data',bits,f'wd_q[{bits*i} +: {bits}]')
    if ports!=expected:raise ValueError('not the full BOOM parent port contract')
    return f'''module rf_boundary(input clock, input [{7*readers-1}:0] raddr,
 input [{writers-1}:0] wen, input [{7*writers-1}:0] waddr,
 input [{bits*writers-1}:0] wdata, output reg [{bits*readers-1}:0] rdata);
 reg [{7*readers-1}:0] ra_q; reg [{writers-1}:0] we_q;
 reg [{7*writers-1}:0] wa_q; reg [{bits*writers-1}:0] wd_q;
 wire [{bits*readers-1}:0] rd;
 always @(posedge clock) begin
   ra_q <= raddr; we_q <= wen; wa_q <= waddr; wd_q <= wdata; rdata <= rd;
 end
 {parent} rf(\n  '''+',\n  '.join(conns)+'\n );\nendmodule\n'


def prepare(stock,lvt,out):
    if any(out==k or k in out.parents or out in k.parents for k in (stock,lvt)) or out.exists():raise ValueError('fresh directory outside both kits required')
    ref=json.loads((HERE.parent/'docs/perf-mega175-regfile-input.json').read_bytes()); h=KIT['h']
    a,b=KIT['seals'](stock),KIT['seals'](lvt); mf='CANDIDATE.sha256'
    if (h(stock/mf)!=ref['stock_board_seal'] or h(lvt/mf)!=ref['candidate_board_input_seal'] or set(a)-set(b)
            or {k:v for k,v in b.items() if a.get(k)!=v}!=ref['changed_or_added']):raise ValueError('incorrect stock/LVT pair')
    vendor='shell/xilinx/vcu118/tcl/board.tcl'
    if 'set part_fpga {xcvu9p-flga2104-2L-e}' not in (stock/vendor).read_text().splitlines():raise ValueError('different device')
    out.mkdir(); modes={}
    for bits,nr,nw,_,parent in RF['PROFILES']:
        leaf=f'regfile_128x{bits}.sv'; par=parent+'.sv'
        wrap=wrapper(bits,nr,nw,parent,(stock/'rtl'/par).read_text()).encode(); common=None
        for name,kit in [('stock',stock),('lvt',lvt)]:
            case=out/f'{bits}-{name}';case.mkdir();copy=[leaf,par]+(['vcu_lvt_regfile.v'] if name=='lvt' else [])
            for f in copy:shutil.copyfile(kit/'rtl'/f,case/f)
            (case/'rf_boundary.v').write_bytes(wrap);(case/'rf.xdc').write_bytes(XDC.encode())
            shutil.copyfile(HERE/'implement-mega-regfile-ooc.tcl',case/'run.tcl')
            ids={p.name:h(p) for p in sorted(case.iterdir(),key=lambda path:path.name)};shared={n:ids[n] for n in (par,'rf_boundary.v','rf.xdc','run.tcl')}
            if common is not None and common!=shared:raise ValueError('not comparable parent/constraints')
            common=shared;(case/mf).write_bytes(''.join(f'{v}  {k}\n' for k,v in ids.items()).encode());modes[case.name]=dict(fixture_sha256=h(case/mf),files=ids)
    return dict(scope='Standalone registered input/output boundaries around the true register-file parent and bypass. Preparation only. Synthetic zero external delays, a common assumed clock buffer site, no physical board I/O or SoC timing.',part='xcvu9p-flga2104-2L-e',period_ns='5.714',stock_seal=h(stock/mf),lvt_seal=h(lvt/mf),cases=modes)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('stock','lvt','out'):p.add_argument(k,type=Path)
    a=p.parse_args();result=prepare(*(v.resolve() for v in vars(a).values()));(a.out/'fixtures.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('FOUR_REGISTERED_OOC_FIXTURES_PREPARED_NOT_IMPLEMENTED')
