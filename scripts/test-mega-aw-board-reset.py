#!/usr/bin/env python3
"""Check actual board reset/AXI wiring, then replay its reset cone against the AW queue."""
import argparse
import json
from pathlib import Path
import re
import runpy
import subprocess

HERE=Path(__file__).resolve().parent
T=runpy.run_path(str(HERE/'test-mega-aw-reset.py'))
S,D=T['S'],T['D']
R='ResetWrangler'; TOP='VCU118FPGATestHarness'; MIG='XilinxVCU118MIG'; ISLAND=MIG+'Island'
AS='AXI4AsyncCrossingSource'; AK='AXI4AsyncCrossingSink'
wr0='_dutWrangler_auto_out_0_reset'; wr1='_dutWrangler_auto_out_1_reset'; wc='_dutWrangler_auto_out_0_clock'
uc='_mig_io_port_c0_ddr4_ui_clk'; ur=uc+'_sync_rst'; ic='_island_io_port_c0_ddr4_ui_clk'; ir=ic+'_sync_rst'
awready='_blackbox_c0_ddr4_s_axi_awready'; awvalid='_axi4asink_auto_out_aw_valid'
PINS=[(TOP,R,'dutWrangler',dict(auto_in_1_clock=uc,auto_in_1_reset=ur,auto_in_0_clock='_harnessSysPLL_clk_out1',
        auto_in_0_reset='~_harnessSysPLL_locked | harnessSysPLLIn_reset',auto_out_0_reset=wr0,auto_out_1_reset=wr1,auto_out_0_clock=wc)),
      (TOP,MIG,'mig',dict(clock=wc,reset=wr0,io_port_c0_ddr4_ui_clk=uc,io_port_c0_ddr4_ui_clk_sync_rst=ur,io_port_c0_ddr4_aresetn='~'+wr1)),
      (MIG,AS,'axi4asource',dict(clock='clock',reset='reset')),
      (MIG,ISLAND,'island',dict(clock=ic,reset=ir,io_port_c0_ddr4_ui_clk=ic,io_port_c0_ddr4_ui_clk_sync_rst=ir,io_port_c0_ddr4_aresetn='io_port_c0_ddr4_aresetn')),
      (ISLAND,AK,'axi4asink',dict(clock='clock',reset='reset',auto_out_aw_ready=awready,auto_out_aw_valid=awvalid)),
      (ISLAND,'vcu118mig','blackbox',dict(c0_ddr4_ui_clk='io_port_c0_ddr4_ui_clk',c0_ddr4_ui_clk_sync_rst='io_port_c0_ddr4_ui_clk_sync_rst',
                c0_ddr4_aresetn='io_port_c0_ddr4_aresetn',c0_ddr4_s_axi_awready=awready,c0_ddr4_s_axi_awvalid=awvalid)),
      (AS,S,'nodeOut_aw_source',dict(clock='clock',reset='reset')),
      (AK,D,'nodeOut_aw_sink',dict(clock='clock',reset='reset',io_deq_valid='auto_out_aw_valid',io_deq_ready='auto_out_aw_ready'))]
UNITS=[*T['UNITS'],R,'AsyncResetReg','AsyncResetRegVec_w15_i0','ResetCatchAndSync_d3','AsyncResetSynchronizerShiftReg_w1_d3_i0']
TEMPLATE=HERE.parent/'tests/mega_aw_wrangler_tb.sv.in'


def inspect(kit):
    modules={name: re.sub(r'//[^\n]*','',(kit/'rtl'/(name+'.sv')).read_text()) for name,_,_,_ in PINS}
    for parent,typ,inst,fields in PINS:
        body=re.findall(r'^\s*'+typ+r'\s+'+inst+r'\s*\(\s*\n(.*?)^\s*\);',modules[parent],re.M|re.S)
        if len(body)!=1: raise ValueError('ambiguous instance: '+inst)
        for name,pin in fields.items():
            if re.findall(r'^\s*\.'+name+r'\s*\(([^\n]*)\),?\s*$',body[0],re.M)!=[pin]:
                raise ValueError('mismatched pin '+inst+'.'+name)
    for port,node in [('io_port_c0_ddr4_ui_clk',ic),('io_port_c0_ddr4_ui_clk_sync_rst',ir)]:
        if modules[MIG].count('assign '+port+' = '+node+';')!=1: raise ValueError('MIG return path')
    return sum(len(f) for _,_,_,f in PINS)


def run(stock,candidate,out,tools):
    h=T['h']; ids=[h((k/'CANDIDATE.sha256').read_bytes()) for k in (stock,candidate)]
    if ids!=T['SEALS']: raise ValueError('incorrect sealed kit pair')
    check=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']; a,b=check(stock),check(candidate)
    names=sorted(set(UNITS)|{x[0] for x in PINS}); rtl={n:b['rtl/'+n+'.sv'] for n in names}
    if any(a['rtl/'+n+'.sv']!=v for n,v in rtl.items()): raise ValueError('board reset cone changed')
    count=inspect(candidate)
    if out.exists() or any(k in out.parents or out in k.parents for k in (stock,candidate)): raise ValueError('fresh disjoint output required')
    out.mkdir(); tb=out/'tb.sv'; tb.write_text(TEMPLATE.read_text().replace('// AW_DUT',T['connections']())); exe=out/'test.vvp'
    lib=tools/'usr/lib/x86_64-linux-gnu/ivl'; bindir=tools/'usr/bin'; inputs=[candidate/'rtl'/(n+'.sv') for n in UNITS]
    subprocess.run([bindir/'iverilog','-B',lib,'-g2012','-DSYNTHESIS','-s','tb','-o',exe,tb,*inputs],check=True)
    results={}
    for hs,hd,phase in T['NUMBERS']:
        for gate in (0,1):
            key=f'{hs}-{hd}-{phase}-{gate}'; p=subprocess.run([bindir/'vvp','-M',lib,exe,f'+HS={hs}',f'+HD={hd}',f'+PH={phase}',f'+GATE={gate}'],capture_output=True,text=True,timeout=25)
            text=p.stdout+p.stderr; (out/(key+'.log')).write_text(text)
            m=re.search(r'^WR_AW_RESULT gate=(\d) source_edges_to_release=(\d+) ui_reset_enqueues=(\d+) cpu_reset_awvalid_edges=(\d+) cpu_reset_handshakes=(\d+) drained=(\d+)$',text,re.M)
            if p.returncode or 'FATAL:' in text or not m or tuple(map(int,m.groups()))!=(gate,17504,0,3,0 if gate else 3,81): raise ValueError(key+': '+text[:350])
            results[key]=dict(zip(('gate_ready_with_aresetn','source_edges_to_release','ui_reset_enqueues','cpu_reset_awvalid_edges','cpu_reset_handshakes','drained'), map(int,m.groups())))
    return dict(scope='ResetWrangler and real AW queue in RTL; synthetic reset causes below PLL/MIG outputs, two explicit MIG AWREADY stimuli. No MIG IP model, silicon, metastability, recovery/removal signoff or throughput.',
        stock_and_candidate_sha256=ids,rtl_sha256=rtl,checked_parent_instance_pins=count,checked_mig_passthroughs=2,
        bench_sha256=h(tb.read_bytes()),cases_by_source_half_sink_half_phase_ps_and_ready_gate=results)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('stock','candidate','out','icarus_root'): p.add_argument(n,type=Path)
    a=p.parse_args(); result=run(*(getattr(a,n).resolve() for n in ('stock','candidate','out','icarus_root')))
    text=json.dumps(result,indent=2)+'\n'; (a.out/'result.json').write_text(text); print(text,end='')
