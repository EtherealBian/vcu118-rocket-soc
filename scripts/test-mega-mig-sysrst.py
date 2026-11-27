#!/usr/bin/env python3
"""Exercise the generated four-wide build's DDR infrastructure reset ahead of its MMCM."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

SEAL = 'ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456'
XDC = 'par/vcu118mig.xdc'
CORE, TOP, INF = ('rtl/ip_top/vcu118mig_ddr4.sv', 'rtl/ip_top/vcu118mig.sv', 'rtl/clocking/ddr4_v2_2_infrastructure.sv')
FAMILY = 'ddr4_v2_2_24_infrastructure'
CLOCK = {'CLKIN_PERIOD_MMCM':'4000', 'CLKFBOUT_MULT_MMCM':'8', 'DIVCLK_DIVIDE_MMCM':'2',
         **{f'CLKOUT{n}_DIVIDE_MMCM':'5' for n in range(5)}, 'CLKOUT6_DIVIDE_MMCM':'10', 'C_FAMILY':'"virtexuplus"', 'TCQ':'100'}
TEMPLATE = Path(__file__).resolve().parent.parent/'tests/mega_mig_sysrst.sv'


def need(ok, why):
    if not ok:
        raise ValueError(why)


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def instance(text, module, name):
    blocks = re.findall(r'\b'+module+r'\s+'+name+r'\s*\(([^;]+)\);', text, re.S)
    need(len(blocks)==1, 'not a unique instance: '+name)
    return blocks[0]


def pin(block, port, signal):
    need(len(re.findall(r'\.'+port+r'\s*\(\s*'+re.escape(signal)+r'\s*\)', block))==1, 'wrong connection: '+port)


def run(kit, old_ip, new_ip, vivado, out):
    need(all(p!=out and p not in out.parents and out not in p.parents for p in (kit,old_ip,new_ip,vivado)), 'overlapping output')
    seal=kit/'CANDIDATE.sha256'; need(digest(seal)==SEAL, 'wrong board inputs'); lines=seal.read_text().splitlines()
    inputs={}; hdl={}
    for n in ('VCU118FPGATestHarness','XilinxVCU118MIG','XilinxVCU118MIGIsland'):
        path=kit/'rtl'/(n+'.sv'); inputs[n]=digest(path); need(f'{inputs[n]}  rtl/{n}.sv' in lines, n); hdl[n]=re.sub(r'//[^\n]*','',path.read_text())
    harness, mig, island=hdl.values(); pin(instance(harness,'IBUF','IBUF'),'I','reset'); pin(instance(harness,'IBUF','IBUF'),'O','_IBUF_O')
    pin(instance(harness,'PowerOnResetFPGAOnly','fpga_power_on'),'power_on_reset','_fpga_power_on_power_on_reset')
    need(re.search(r'assign\s+harnessSysPLLIn_reset\s*=\s*_IBUF_O\s*\|\s*_fpga_power_on_power_on_reset\s*;',harness),'reset merge changed')
    pin(instance(harness,'XilinxVCU118MIG','mig'),'io_port_sys_rst','harnessSysPLLIn_reset')
    pin(instance(mig,'XilinxVCU118MIGIsland','island'),'io_port_sys_rst','io_port_sys_rst')
    pin(instance(island,'vcu118mig','blackbox'),'sys_rst','io_port_sys_rst')
    generated={p:digest(new_ip/p) for p in (TOP,CORE,INF,XDC)}
    need(all(digest(old_ip/p)==h for p,h in generated.items()),'differing generated IP inputs')
    core=(new_ip/CORE).read_text(); top=(new_ip/TOP).read_text(); inf=(new_ip/INF).read_text()
    pin(instance(top,'vcu118mig_ddr4','inst'),'sys_rst','sys_rst')
    block=re.findall(r'\b'+FAMILY+r'\s*#\s*\((.*?)\)\s*u_ddr4_infrastructure\s*\(([^;]+)\);',core,re.S)
    need(len(block)==1,'missing MIG clock/reset leaf'); params,ports=block[0]; pin(ports,'sys_rst','sys_rst'); pin(ports,'sys_clk_in','sys_clk_in')
    need(set(re.findall(r'\.(\w+)\s*\(',params))==set(CLOCK),'other parameter overrides')
    for n,v in CLOCK.items():
        pin(params,n,n); need(re.findall(r'\bparameter\s+(?:real\s+)?'+n+r'\s*=\s*([^,]+?)\s*,',core)==[v], 'wrong parent parameter: '+n)
    need((new_ip/XDC).read_text().splitlines()[294].strip()=='set_false_path -through [get_pins u_ddr4_infrastructure/sys_rst]', 'changed exception')
    out.mkdir(); pattern='always @(posedge sys_clk_in_bufg or posedge sys_rst )'; need(inf.count(pattern)==1,'nonunique second stage')
    tb=TEMPLATE.read_text(); need(tb.count('// ACTUAL_PARAMETERS')==1,'wrong test fixture')
    tb=tb.replace('// ACTUAL_PARAMETERS', ',\n    '.join(f'.{n}({v})' for n,v in CLOCK.items())); glbl=vivado/'data/verilog/src/glbl.v'
    ext='.bat' if os.name=='nt' else ''
    def tool(work,name,args,label,negative=None):
        cp=subprocess.run([str(vivado/'bin'/(name+ext)),*map(str,args)],cwd=work,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=150)
        (work/(label+'.log')).write_bytes(cp.stdout); text=cp.stdout.decode(errors='replace'); fails=re.findall(r'(?im)^\s*(?:fatal|error):\s*(.*)$',text)
        if negative is None:
            need(cp.returncode==0 and not fails, f'{label} failed in {work.name}')
        else:
            need(fails and fails[0].strip()==negative and 'MIG_SYSRST_FIXTURE_COMPLETE' not in text, 'wrong negative control: '+label)
        return text
    logs={}; results=[]
    for variant in ('actual','second_synchronous_only'):
        work=out/variant; work.mkdir(); src=new_ip/INF
        if variant!='actual':
            src=work/'mutated.sv'; src.write_bytes(inf.replace(pattern,'always @(posedge sys_clk_in_bufg)').encode())
        (work/'tb.sv').write_bytes(tb.encode())
        tool(work,'xvlog',['--sv',src,'tb.sv'],'compile'); tool(work,'xvlog',[glbl],'glbl')
        e=tool(work,'xelab',['tb','glbl','-L','unisims_ver','--mt','off','--timescale','1ps/1ps','-s','migreset'],'elab'); need(all(tag in e for tag in ('Vivado Simulator v2024.2','Built simulation snapshot migreset','Compiling module unisims_ver.MMCME4_ADV','Compiling module unisims_ver.BUFG')), 'wrong primitives or elaboration')
        if variant=='actual':
            txt=tool(work,'xsim',['migreset','--runall'],'actual'); rows=re.findall(r'^RESET_RELEASE case=(\d+) edges=57 async_clear=2 stretch_last_full=6 design_clear=57\s*$',txt,re.M)
            need(rows==list(map(str,range(6))) and txt.splitlines().count('MIG_SYSRST_FIXTURE_COMPLETE')==1 and '$finish called' in txt,'missing coverage')
            warnings=re.findall(r'(?im)^warning:\s+\[([^\]]+)\]',txt); need(warnings==['Unisim MMCME4_ADV-39'],'unexpected runtime warning inventory')
            results=['stopped-clock external pulse','sub-cycle POR only','overlapping external and POR','release after one rising edge','release while clock stopped','reassert during stretch']
            tool(work,'xsim',['migreset','--testplusarg','DROP_POR','--runall'],'drop_por','PRESET_MISSING case=1')
        else:
            tool(work,'xsim',['migreset','--runall'],'missing_preset','PRESET_MISSING case=0')
        logs[variant]={p.name:digest(p) for p in work.glob('*.log') if p.stem in ('compile','glbl','elab','actual','drop_por','missing_preset')}
    return dict(scope='Generated MIG clock/reset infrastructure only, simulated buffered 4 ns reference, fixed PLL-lock input. No PHY/calibration, DDR, metastability, recovery/removal margin or new routed signoff.',
        candidate_seal_sha256=SEAL,kit_rtl_sha256=inputs,matching_generated_ip_sha256=generated,parameters=CLOCK,fixture_sha256=sha256(tb.encode()).hexdigest(),glbl_sha256=digest(glbl),
        cases=results,positive_run_warnings=warnings,release_edges=dict(async_pair_idle=2,stretch_counter_last_at_50=6,design_reset_low=57),negative_controls={'drop_por':'PRESET_MISSING case=1','second_synchronous_only':'PRESET_MISSING case=0'},log_sha256=logs)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); names=('kit','old_ip','new_ip','vivado','out')
    for n in names: ap.add_argument(n,type=Path)
    args=ap.parse_args(); result=run(*(getattr(args,n).resolve() for n in names)); (args.out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode()); print('MIG_RESET_COMPARE_COMPLETE',len(result['cases']))
