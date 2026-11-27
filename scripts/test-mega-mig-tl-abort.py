#!/usr/bin/env python3
"""Exercise the sealed TileLink-to-DDR write path through the generated MIG AXI front end."""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'test-mega-mig-aw-pins.py'))
T = M['T']; h = T['h']; need = M['need']
BENCH = HERE.parent / 'tests/mega_mig_tl_abort_tb.sv'


def cone(kit, seals):
    seen = set(); todo = ['ResetWrangler', 'XilinxVCU118MIG']
    while todo:
        name = todo.pop()
        if name in seen: continue
        seen.add(name); f = kit / 'rtl' / (name + '.sv')
        for child in re.findall(r'^  (\w+) \w+ \(', f.read_text(), re.M):
            if child != 'vcu118mig':
                need('rtl/' + child + '.sv' in seals, 'unexpected black box ' + child)
                todo.append(child)
    need(len(seen)==41 and {'TLToAXI4','AXI4AsyncCrossingSource','AXI4AsyncCrossingSink','AXI4IdIndexer','AXI4UserYanker'} <= seen,
         'incomplete bridge')
    return [str('rtl/'+name+'.sv') for name in sorted(seen)]


def shim(ip):
    # Reuse the exact local black box port declarations. No PHY, MMCM, calibration or DDR memory is simulated.
    top = (ip / M['TOP']).read_text(); header = re.search(r'\bmodule vcu118mig\s*\(.*?\);',top,re.S).group()
    axi_ports = re.findall(r'\bc0_ddr4_(s_axi_\w+)\s*[,\n]',header)
    need(len(set(axi_ports))==len(axi_ports)==37, 'AXI interface differs')
    params = ','.join('.'+child+'('+val+')' for child,(_,val) in M['PARAMS'].items())
    wires = {p:'c0_ddr4_'+p for p in axi_ports}
    wires.update(aclk='c0_ddr4_ui_clk',aresetn='c0_ddr4_aresetn',s_axi_aruser="1'b0",s_axi_awuser="1'b0",
                 mc_init_complete="1'b1",mc_app_rdy='tb.mc_ready',mc_app_wdf_rdy='tb.data_ready',mc_app_en='en',mc_app_cmd='cmd',
                 mc_app_addr='ma',mc_app_wdf_wren='we',mc_app_wdf_mask='mask',mc_app_wdf_data='bits',mc_app_wdf_end='last',
                 mc_app_rd_valid="1'b0",mc_app_rd_data="512'b0",mc_app_rd_end="1'b0",mc_app_ecc_multiple_err="8'b0")
    return ('`timescale 1ps/1ps\n'+header+'\nwire [27:0] ma; wire [2:0] cmd; wire en,we,last; wire [511:0] bits; wire [63:0] mask;\n'
            "assign c0_init_calib_complete=1'b1; assign c0_ddr4_ui_clk=c0_sys_clk_i; assign c0_ddr4_ui_clk_sync_rst=sys_rst;\n"
            +'ddr4_v2_2_24_axi #('+params+') ip('+',\n'.join('.'+k+'('+v+')' for k,v in wires.items())+');\nendmodule\n')


def parse(text, scenario, clocks, abort):
    need('$finish called' in text and not re.search(r'(?im)^\s*(fatal:|error:)',text), 'incomplete simulation')
    rows = re.findall(r'^BRIDGE_RESULT (.*)$',text,re.M); need(len(rows)==1,'missing unique result')
    row = {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',rows[0])}
    need([row[k] for k in ('abort','scenario','hs','hd','phase')]==[abort,scenario,*clocks] and
         [row[k] for k in ('pre_aw','pre_w','late_d','clean')]==[1,1,1-abort,2], 'wrong coverage')
    for k,pre,late in [('cmds','pre_cmd','late_cmd'),('datas','pre_data','late_data')]:
        need(row[k]==2+row[pre]+row[late] and row[pre]<=1 and (row[late]==0 if abort else row[k]==3),'MC accounting')
    need((scenario not in (0,2) or row['pre_cmd']==0) and (scenario not in (0,3) or row['pre_data']==0) and
         (scenario!=1 or all(row[k]==1 for k in ('pre_cmd','pre_data','pre_b','pre_dvalid'))), 'wrong backpressure')
    need(row['fifo_mixed_pairs']==int(abort and row['pre_cmd']!=row['pre_data']),'FIFO pairing accounting')
    return row


def run(kit, old, ip, vivado, out):
    lock = json.loads((HERE.parent/'docs/perf-mega175-mig-aw-pins.json').read_bytes())
    need(h((kit/'CANDIDATE.sha256').read_bytes())==lock['candidate_seal']==T['SEALS'][1], 'wrong kit')
    seals=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals'](kit); M['WR']['inspect'](kit)
    keys, dig = M['ip_sources'](old,ip); need(dig==lock['generated_ip_inputs'], 'MIG source drift')
    closure=cone(kit,seals); wrapper=shim(ip)
    need(not out.exists() and not any(k==out or k in out.parents or out in k.parents for k in (kit,old,ip,vivado)),'fresh disjoint output required')
    out.mkdir(); box=out/'test_controller.sv'; box.write_bytes(wrapper.encode()); ext='.bat' if os.name=='nt' else ''
    def invoke(name, args, label, negative=False):
        p=subprocess.run([str(vivado/'bin'/(name+ext)),*map(str,args)],cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
        (out/(label+'.log')).write_bytes(p.stdout); text=p.stdout.decode(errors='replace')
        if negative:
            need(re.search(r'(?im)^\s*fatal: bad W\b',text) and 'BRIDGE_RESULT' not in text, 'wrong negative-control outcome'); return text
        need(p.returncode==0 and not re.search(r'(?im)^\s*(error:|fatal:)',text),label+' failed; inspect log'); return text
    glbl=vivado/'data/verilog/src/glbl.v'; need(h(glbl.read_bytes())==lock['glbl_sha256'],'wrong glbl')
    invoke('xvlog',['--sv','-d','SYNTHESIS',*[kit/n for n in closure],*[ip/n for n in keys],box,BENCH],'compile')
    invoke('xvlog',[glbl],'glbl')
    elab=invoke('xelab',['tb','glbl','-L','unisims_ver','-L','unimacro_ver','-L','xpm','--mt','off','--timescale','1ps/1ps','-s','bridge'],'elab')
    need('Vivado Simulator v2024.2' in elab and 'Built simulation snapshot bridge' in elab,'wrong simulator')
    cases=[]
    for i,clk in enumerate(T['NUMBERS']):
        for scenario,mode in enumerate(('BLOCKMC','PENDACK','BLOCKCMD','BLOCKDATA')):
            for abort,action in enumerate(('DRAIN','ABORT')):
                args=['bridge','--testplusarg',f'CASE{i}','--testplusarg',mode,'--testplusarg',action,'--runall']
                cases.append(parse(invoke('xsim',args,f'case{i}-{scenario}-{abort}'),scenario,clk,abort))
    invoke('xsim',['bridge','--testplusarg','CASE0','--testplusarg','PENDACK','--testplusarg','ABORT',
                   '--testplusarg','BADPAYLOAD','--runall'],'negative-payload',negative=True)
    return dict(scope='Sealed TileLink PutFullData through complete bridge and generated MIG AXI RTL. Two continuous clocks, modeled calibration/MC ready; no DDR PHY, persisted memory, metastability or timing/board signoff.',
                seal=T['SEALS'][1],bridge={n:seals[n] for n in closure},ip_receipt_sha256=h((HERE.parent/'docs/perf-mega175-mig-aw-pins.json').read_bytes()),
                bench_sha256=h(BENCH.read_bytes()),shim_sha256=h(box.read_bytes()),negative_corrupt_post_reset_data='bad W',cases=cases)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); names=('candidate','old_ip','new_ip','vivado','out')
    for n in names: p.add_argument(n,type=Path)
    a=p.parse_args(); result=run(*(getattr(a,n).resolve() for n in names)); text=json.dumps(result,indent=2)+'\n'
    (a.out/'result.json').write_bytes(text.encode()); print(text,end='')
