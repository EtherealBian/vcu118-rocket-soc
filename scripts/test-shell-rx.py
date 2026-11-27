#!/usr/bin/env python3
"""Test the unedited VCU118 outer harness using xsim; replace unrelated blocks by empty interfaces."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
TOP = 'VCU118FPGATestHarness.sv'
IO = ('AnalogToUInt_1.v','UIntToAnalog_1.v','PowerOnResetFPGAOnly.v','plusarg_reader.v')
EMPTY = ('ChipTop','ResetWrangler','XilinxVCU118MIG','ResetCatchAndSync_d3')
TB = HERE.parent/'tests/shell_rx_tb.v'

def digest(p): return sha256(p.read_bytes()).hexdigest()

def fixture(stock):
    rtl = stock/'rtl'; xdc, = (stock/'board').glob('*.shell.xdc')
    top,xdc_out,synth_out = runpy.run_path(str(HERE/'board_shell_overlay.py'))['transform'](
        (rtl/TOP).read_bytes(),xdc.read_bytes(),(stock/'shell/xilinx/common/tcl/synth.tcl').read_bytes())
    # No behavioral replacement for the pad converter or outer harness. Only
    # the receiving port is observed; PLL, DDR, reset logic and CPU are not tested.
    stubs = []
    for name in EMPTY:
        text = re.sub(r'//[^\n]*','',(rtl/(name+'.sv')).read_text())
        headers=re.findall(r'^module '+name+r'\s*\([^;]+?\);',text,re.M)
        if len(headers)!=1: raise ValueError('unknown interface: '+name)
        stubs.append(headers[0]+'\nendmodule\n')
    stubs.extend(['module harnessSysPLL(input clk_in1, input reset, output clk_out1, output locked); endmodule',
                  'module IBUF(input I, output O); endmodule',
                  'module IBUFDS #(parameter CAPACITANCE="", DIFF_TERM="", DQS_BIAS="", IBUF_DELAY_VALUE=0, IBUF_LOW_PWR="", IFD_DELAY_VALUE="", IOSTANDARD="") (input I,IB, output O); endmodule'])
    return top,'\n'.join(stubs)

def run(stock,out,tools):
    stock=stock.resolve(strict=True); tools=tools.resolve(strict=True); out=out.resolve(); out.mkdir()
    corrected,stubs=fixture(stock); records={}
    for name,stages,data in [('raw',0,(stock/'rtl'/TOP).read_bytes()),('fixed',2,corrected)]:
        work=out/name; work.mkdir(); h=work/TOP; h.write_bytes(data); stub=work/'boundaries.v';stub.write_bytes(stubs.encode())
        def execute(tool,args,log):
            with (work/log).open('xb') as f:
                subprocess.run([str(tools/(tool+'.bat')),*map(str,args)],cwd=work,stdout=f,stderr=subprocess.STDOUT,check=True)
            return (work/log).read_text(errors='replace')
        inputs=[h,stub,TB,*[stock/'rtl'/n for n in IO]]
        execute('xvlog',['-sv','-d','SYNTHESIS',*inputs],'compile.txt')
        execute('xelab',['--mt','off','--timescale','1ps/1ps','work.shell_rx_tb','-s','shellrx'],'elab.txt')
        cases=[]
        for half in (5000,2857):
            for expected in (stages,2-stages):
                text=execute('xsim',['shellrx','-testplusarg',('two_edges' if expected==2 else 'zero_edges'),'-testplusarg',('clk175' if half==2857 else 'clk100'),'-runall'],f'run-{half}-{expected}.txt')
                passed=re.findall(r'^RX_LATENCY_PASS stages=(\d+) half_ps=(\d+) samples=(\d+) distinguishable=(\d+)$',text,re.M)
                rejected=re.findall(r'^RX_LATENCY_MISMATCH sample=(\d+) expected=([01]) observed=([01])$',text,re.M)
                if expected==stages:
                    if len(passed)!=1 or rejected or list(map(int,passed[0][:3]))!=[stages,half,1025] or int(passed[0][3])<100:raise ValueError('incomplete pin test')
                    cases.append(dict(half_period_ps=half,samples=1025,different_from_other_latency=int(passed[0][3])))
                elif passed or len(rejected)!=1 or rejected[0][1]==rejected[0][2]:raise ValueError('wrong latency not rejected')
        records[name]=dict(expected_stages=stages,inputs={p.name:digest(p) for p in inputs},positive=cases,wrong_latency_rejected=2)
    return dict(scope='xsim digital pad-to-ChipTop RX latency. Full outer HDL and real pad converter; forced receiving clock, CPU/DDR/PLL excluded. Not metastability, routed timing, UART firmware or board performance.',cases=records)

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for key in ('stock','out','vivado_bin'):a.add_argument(key,type=Path)
    p=a.parse_args(); print(json.dumps(run(p.stock,p.out,p.vivado_bin),indent=2))
