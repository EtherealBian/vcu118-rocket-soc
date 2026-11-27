#!/usr/bin/env python3
"""Probe CPU-only reset at the real generated MIG AXI front-end pins (no DDR PHY)."""
import argparse
from pathlib import Path
import json
import os
import re
import runpy
import subprocess

HERE=Path(__file__).resolve().parent
WR=runpy.run_path(str(HERE/'test-mega-aw-board-reset.py')); T=WR['T']; h=T['h']
TEMPLATE=HERE.parent/'tests/mega_aw_mig_boundary_tb.sv.in'
TOP='rtl/ip_top/vcu118mig.sv'; CORE='rtl/ip_top/vcu118mig_ddr4.sv'; AXI='rtl/axi/ddr4_v2_2_axi.sv'
PINS={TOP:'ea105daaac424b41d3d08db77b780db80ca029a64458ba5011187ccb7b663fbe',
      CORE:'6911567d1d38847a9056c55c5f9d2ba866cee58893d1c1dc666422e5f4442391',
      AXI:'79bbbb81c3fd9e207d775b259529241a65996b5fb925344359b35e0522c842d6',
      'vcu118mig.xci':'be47ca3d0594b66ea2d1a1afe97b6ba7bf29f6db512fccb1b02539e4c734bd28'}
PARAMS={'C_ECC':('ECC','"OFF"'), 'C_S_AXI_ID_WIDTH':('C_S_AXI_ID_WIDTH','4'),
        'C_S_AXI_ADDR_WIDTH':('C_S_AXI_ADDR_WIDTH','31'), 'C_S_AXI_DATA_WIDTH':('C_S_AXI_DATA_WIDTH','64'),
        'C_MC_ADDR_WIDTH':('APP_ADDR_WIDTH','28'), 'C_MC_DATA_WIDTH':('APP_DATA_WIDTH','512'),
        'C_MC_BURST_MODE':('BURST_MODE','"8"'), 'C_MC_nCK_PER_CLK':('nCK_PER_CLK','4'),
        'C_S_AXI_SUPPORTS_NARROW_BURST':('C_S_AXI_SUPPORTS_NARROW_BURST','0'),
        'C_RD_WR_ARB_ALGORITHM':('C_RD_WR_ARB_ALGORITHM','"RD_PRI_REG"'),
        'C_S_AXI_REG_EN0':('C_S_AXI_REG_EN0',"20'h00000"), 'C_S_AXI_REG_EN1':('C_S_AXI_REG_EN1',"20'h00000")}


def need(pred,msg):
    if not pred: raise ValueError(msg)


def ip_sources(old,new):
    keys=sorted(p.relative_to(new).as_posix() for p in (new/'rtl/axi').glob('*.sv'))
    need(keys==sorted(p.relative_to(old).as_posix() for p in (old/'rtl/axi').glob('*.sv')) and len(keys)>=20,'different AXI source set')
    dig={n:h((new/n).read_bytes()) for n in sorted(set(keys)|PINS.keys())}
    need(all(dig[k]==h((old/k).read_bytes()) for k in dig) and all(dig[k]==v for k,v in PINS.items()),'generated IP mismatch')
    core=(new/CORE).read_text(); top=(new/TOP).read_text(); fixture=TEMPLATE.read_text()
    need(re.search(r'\bvcu118mig_ddr4\s+inst\s*\(',top),'board parent overrides may be present')
    for child,(parent,val) in PARAMS.items():
        need(re.search(r'\.\s*'+child+r'\s*\(\s*'+parent+r'\s*\)',core) and
             re.search(r'\bparameter\s+(?:integer\s+)?'+parent+r'\s*=\s*'+re.escape(val)+r'\s*,',core) and
             '.'+child+'('+val+')' in fixture,'parameter mismatch: '+child)
    for n,wire in [('aresetn','c0_ddr4_aresetn'),('s_axi_awvalid','c0_ddr4_s_axi_awvalid'),('s_axi_awready','c0_ddr4_s_axi_awready'),
                   ('s_axi_aruser',"1'b0"),('s_axi_awuser',"1'b0"),('mc_init_complete','c0_init_calib_complete')]:
        need(re.search(r'\.'+n+r'\s*\(\s*'+re.escape(wire)+r'\s*\)',core),'wrong MIG bridge: '+n)
    for clk in ('aclk','c0_ddr4_ui_clk'):
        need(re.search(r'assign\s+'+clk+r'\s*=\s*c0_div_clk\s*;',core),'wrong AXI domain')
    return keys,dig


def parse(text,index,clocks):
    need(not re.search(r'(?im)^\s*(fatal:|error:)',text) and '$finish called' in text,'incomplete/failed simulation')
    rows=re.findall(r'^MIG_EDGE (\d+) ([01]) ([01]) ([01])\s*$',text,re.M)
    need([int(x[0]) for x in rows]==list(range(10)) and all(r=='0' for _,r,_,_ in rows),'missing/unknown samples')
    waves=[''.join(row[i] for row in rows) for i in (2,3)]
    valid=waves[0].count('1'); both=sum(v==r=='1' for v,r in zip(*waves))
    m=re.findall(r'^MIG_AW_RESULT case=(\d+) hs=(\d+) hd=(\d+) phase=(\d+) pending_edges=(\d+) pin_overlaps=(\d+) clean_b_responses=(\d+) intervening_mc_requests=(\d+) intervening_mc_data=(\d+)\s*$',text,re.M)
    need(len(m)==1 and tuple(map(int,m[0]))==(index,*clocks,valid,both,2,0,0) and 1<=valid<=3, 'pin totals, coverage or clean controls differ')
    return dict(half_periods_and_phase_ps=list(clocks),aresetn='0'*10,awvalid=waves[0],awready=waves[1],overlap_edges=both,
                clean_writes_with_b_before_after=2,mc_requests_and_data_between_clean_writes_after_reset_assertion=[0,0])


def run(kit,old,new,vivado,out):
    need(h((kit/'CANDIDATE.sha256').read_bytes())==T['SEALS'][1],'wrong board kit')
    seals=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals'](kit); pins=WR['inspect'](kit)
    keys,ip=ip_sources(old,new); need(not out.exists() and not any(k in out.parents or out in k.parents for k in (kit,old,new,vivado)),'fresh output outside inputs required')
    out.mkdir(); tb=out/'tb.sv'; tb.write_bytes(TEMPLATE.read_text().replace('// AW_DUT',T['connections']()).encode()); glbl=vivado/'data/verilog/src/glbl.v'; ext='.bat' if os.name=='nt' else ''
    def invoke(command,args,label,timeout):
        exe=vivado/'bin'/(command+ext); p=subprocess.run([str(exe),*map(str,args)],cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        (out/(label+'.log')).write_bytes(p.stdout); text=p.stdout.decode(errors='replace'); need(p.returncode==0 and not re.search(r'(?im)^\s*ERROR:',text),label+' failed; inspect log'); return text
    files=[kit/'rtl'/(u+'.sv') for u in WR['UNITS']]+[new/n for n in keys]
    invoke('xvlog',['--sv','-d','SYNTHESIS',*files,tb],'compile',180); invoke('xvlog',[glbl],'compile-glbl',120)
    elab=invoke('xelab',['tb','glbl','-L','unisims_ver','-L','unimacro_ver','-L','xpm','--mt','off','--timescale','1ps/1ps','-s','migtb'],'elaborate',180)
    need('Vivado Simulator v2024.2' in elab and 'Built simulation snapshot migtb' in elab,'wrong elaboration')
    cases=[parse(invoke('xsim',['migtb','--testplusarg',f'CASE{i}','--runall'],'case'+str(i),90),i,c) for i,c in enumerate(T['NUMBERS'])]
    return dict(scope='Generated MIG AXI front end with actual AW queue/ResetWrangler and functional vendor libraries. Calibrated, ready application-side model; no DDR PHY/model, external pins, implementation signoff or board score.',
                candidate_seal=T['SEALS'][1],generated_ip_inputs=ip,checked_parent_pins=pins,compared_ip_parameters=len(PARAMS),
                queue_and_wrangler_rtl={u:seals['rtl/'+u+'.sv'] for u in WR['UNITS']},glbl_sha256=h(glbl.read_bytes()),fixture_sha256=h(tb.read_bytes()),cases=cases)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    names=('candidate','old_ip','new_ip','vivado_install','out')
    for n in names: p.add_argument(n,type=Path)
    a=p.parse_args(); result=run(*(getattr(a,n).resolve() for n in names)); text=json.dumps(result,indent=2)+'\n'
    (a.out/'result.json').write_bytes(text.encode()); print(text,end='')
