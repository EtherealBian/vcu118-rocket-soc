#!/usr/bin/env python3
"""Trace the reported Medium reset crossing in its exported routed SDF/netlist.

This is a topology/Boolean check, NOT an analog CDC waiver or board gate. Do not
use this baseline's conclusions for another implementation without tracing it.
"""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
TOP = 'VCU118FPGATestHarness'
MIG = 'mig/island/blackbox/inst/u_ddr4_mem_intfc/u_ddr_mc/bgr[0].u_ddr_mc_group/rst_r1_reg'
POR = 'fpga_power_on/power_on_reset_reg'
PRE = 'dutWrangler/deglitched_deglitch/reg_0_reg'
SYSCLK = 'harnessSysPLL/inst/clkout1_buf/O'
MEMCLK = 'mig/island/blackbox/inst/u_ddr4_infrastructure/u_bufg_divClk/O'
SOURCES = {'pll_locked': 'harnessSysPLL/inst/mmcme4_adv_inst/LOCKED', 'external_reset': 'IBUF/IBUFCTRL_INST/O', 'mig_reset': MIG+'/Q', 'power_on_reset': POR+'/Q'}
CHAINS = ['dutWrangler/nodeOut_reset_catcher'+s+'/io_sync_reset_chain/output_chain/sync_' for s in ('','_1')]

def only(items, label):
    items=list(items)
    if len(items)!=1: raise ValueError('missing or ambiguous '+label)
    return items[0]

def quote_pin(s):
    # Vivado SDF uses backslashes for literal dots and brackets inside a leaf.
    return re.escape(re.sub(r'([.\[\]])', r'\\\1', s).encode('ascii'))

def unquote_pin(raw):
    return re.sub(rb'\\([.\[\]])',rb'\1',raw).decode('ascii')

def trace(sdf, net, reported):
    def drivers(pin):
        # SDF lists an INTERCONNECT for each load. Select by exact sink, then
        # parse its source from that same line (do not infer routing by names).
        needle=b' '+re.sub(r'([.\[\]])', r'\\\1', pin).encode()+b' ('
        start=0
        while True:
            i=sdf.find(needle,start)
            if i<0:return
            start=i+len(needle)
            row=sdf[sdf.rfind(b'\n',0,i)+1:i].strip().split()
            if len(row)!=2 or row[0]!=b'(INTERCONNECT':raise ValueError('malformed incoming arc: '+pin)
            yield unquote_pin(row[1])
    def src(pin):return only(drivers(pin),pin)
    def loads(pin):
        return [unquote_pin(m[1]) for m in re.finditer(rb'\(INTERCONNECT '+quote_pin(pin)+rb' ([^ \r\n]+) ',sdf)]
    def cell(inst):
        needle=b'(INSTANCE '+re.sub(r'([.\[\]])',r'\\\1',inst).encode()+b')'; a=sdf.find(needle)
        if a<0 or sdf.find(needle,a+1)>=0:raise ValueError('missing or duplicate instance '+inst)
        return only(re.findall(rb'\(CELLTYPE "(\w+)"\)\s*$',sdf[max(0,a-110):a]),inst+' type').decode()
    def body(name):
        m=only(re.finditer(rb'(?m)^module '+name.encode()+rb'\s',net),name)
        end=net.find(b'\nendmodule', m.end());
        if end<0:raise ValueError('unterminated '+name)
        return net[m.end():end]
    def bound(text,pattern): return only(re.finditer(pattern,text),pattern.decode())
    if {r['from'] for r in reported}!={MIG+'/C',POR+'/C'} or len(reported)!=2 or any(r['to']!=PRE+'/PRE' or r['severity']!='Critical' or r['rule']!='CDC-7' for r in reported):raise ValueError('different CDC endpoints')
    lut,out=src(PRE+'/PRE').rsplit('/',1)
    if out!='O' or not re.fullmatch('mig/island/[A-Za-z_0-9]+',lut) or cell(lut)!='LUT4' or cell(PRE)!='FDPE':raise ValueError('different preset cone')
    ports=[src(lut+'/I'+str(i)) for i in range(4)]
    if set(ports)!=set(SOURCES.values()) or cell(MIG)!='FDRE' or cell(POR)!='FDRE' or cell('IBUF/IBUFCTRL_INST')!='IBUFCTRL' or cell('harnessSysPLL/inst/mmcme4_adv_inst')!='MMCME4_ADV':raise ValueError('different LUT inputs')
    top=body(TOP); bound(top,rb'\bXilinxVCU118MIG\s+mig\s*\('); bound(body('XilinxVCU118MIG'),rb'\bXilinxVCU118MIGIsland\s+island\s*\(')
    bound(top,rb'\bIBUF_UNIQ_BASE_\s+IBUF\s*\(\s*\.I\(reset\),\s*\.O\(_IBUF_O\)\);')
    b=body('XilinxVCU118MIGIsland'); leaf=re.escape(lut.rsplit('/',1)[1].encode())
    m=bound(b,rb"\bLUT4\s*#\(\s*\.INIT\(16'h([0-9a-fA-F]{4})\)\)\s*"+leaf+rb'\s*\(\s*\.I0\((\w+)\),\s*\.I1\((\w+)\),\s*\.I2\((\w+)\),\s*\.I3\((\w+)\),\s*\.O\(\w+\)\);')
    lut_init=int(m[1],16); aliases={'pll_locked':'locked','external_reset':'_IBUF_O','mig_reset':'rst_r1_alias','power_on_reset':'power_on_reset'}
    for i,pin in enumerate(ports):
        if m[i+2].decode()!=aliases[next(k for k,v in SOURCES.items() if v==pin)]:raise ValueError('SDF and netlist port roles disagree')
    for addr in range(16):
        val={name:(addr>>ports.index(pin))&1 for name,pin in SOURCES.items()}
        want=not val['pll_locked'] or any(val[k] for k in ('external_reset','mig_reset','power_on_reset'))
        if ((lut_init>>addr)&1)!=want:raise ValueError('unexpected reset truth table')
    if src(MIG+'/C')!=MEMCLK or src(POR+'/C')!='_sys_clock_ibufds_O_BUFG_inst/O' or src(PRE+'/C')!=SYSCLK:raise ValueError('unmatched launch/capture clock')
    want=[c+str(i)+'_reg/CLR' for c in CHAINS for i in range(3)]
    if sorted(loads(PRE+'/Q'))!=sorted(want):raise ValueError('different preset register fanout')
    for c,clock in zip(CHAINS,(SYSCLK,MEMCLK)):
        regs=[c+str(i)+'_reg' for i in range(3)]
        for i,r in enumerate(regs):
            if cell(r)!='FDCE' or src(r+'/CLR')!=PRE+'/Q' or src(r+'/C')!=clock:raise ValueError('different reset catcher')
            if i<2 and src(r+'/D')!=regs[i+1]+'/Q':raise ValueError('broken three-stage chain')
    return dict(scope='Original two-wide routed reset topology only. No hazard, metastability, recovery/removal, pin timing, debug crossing, automatic waiver or permission to program.',reported_preset_paths=len(reported),mig_source_flipflop='DDR controller bank group zero reset',merge='LUT4',init_hex=f'{lut_init:04x}',inputs_in_lut_order=[next(k for k,v in SOURCES.items() if v==pin) for pin in ports],truth_table_rows=16,deglitch_primitive='FDPE',deglitch_q_async_clear_loads=6,catchers=[dict(clock=c,flip_flops=3,primitive='FDCE',interstage_data_arcs=2) for c in ('SoC','MIG UI')])

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def review(obj):
    files={'routed_sdf':obj/(TOP+'.sdf'),'routed_verilog':obj/(TOP+'.v'),'cdc_report':obj/'report/cdc.rpt','post_route_dcp':obj/'post_route.dcp','bit':obj/(TOP+'.bit')}
    inventory=runpy.run_path(str(HERE/'inventory-cdc.py'))['inventory'](files['cdc_report'].read_text())
    rows=[r for r in inventory['critical'] if r['rule']=='CDC-7' and r['to']==PRE+'/PRE']
    with files['routed_sdf'].open('rb') as sf, files['routed_verilog'].open('rb') as vf, mmap.mmap(sf.fileno(),0,access=mmap.ACCESS_READ) as s, mmap.mmap(vf.fileno(),0,access=mmap.ACCESS_READ) as v:
        res=trace(s,v,rows)
    res['inputs_sha256']={k:digest(v) for k,v in files.items()}
    prior=json.loads((HERE.parent/'docs/perf-medium-route.json').read_bytes()); h=res['inputs_sha256']
    if (h['bit'],h['cdc_report'])!=(prior['bit_sha256'],prior['reports_sha256']['cdc.rpt']):raise ValueError('not the previously reviewed Medium build')
    return res

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('obj',type=Path);args=p.parse_args();print(json.dumps(review(args.obj),indent=2))
