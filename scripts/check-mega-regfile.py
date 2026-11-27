#!/usr/bin/env python3
"""Isolated 4-state test of two physical register files from the sealed four-wide BOOM.

No default RTL, netlist or bitstream is changed. Test uninitialized reads, X on
masked outputs, same-address priority, independent writes and async read timing.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SEAL='b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'
PROFILES=((64,12,6,'f6eb510b5d9518aea9fc6e5d74ffc1c2ddaaac2406718b2649e364dd4e2ccf45','RegisterFileSynthesizable_1'),
          (65,6,4,'b03b5cdc1a77f009605cbe68225317163926d9e5a9980391ea17b96733053628','RegisterFileSynthesizable'))

def digest(p):return sha256(p.read_bytes()).hexdigest()

def wrapper(d,r,w):
    args=[]
    for pre,num in (('R',r),('W',w)):
        for i in range(num):
            for k,wire in [('clk','clk'),('en',f'{pre.lower()}e[{i}]'),('addr',f'{pre.lower()}a[{i*7}+:7]'),('data',f'{pre.lower()}d[{i*d}+:{d}]')]:
                args.append(f'.{pre}{i}_{k}({wire})')
    return f'module reference_wrapper(input clk,input [{r*7-1}:0] ra,input [{r-1}:0] re,output [{r*d-1}:0] rd,input [{w*7-1}:0] wa,input [{w-1}:0] we,input [{w*d-1}:0] wd);\n regfile_128x{d} dut ('+',\n'.join(args)+');\nendmodule\n'


def review(kit,out,iverilog,vvp,ivl):
    manifest=kit/'CANDIDATE.sha256'
    if digest(manifest)!=SEAL:raise ValueError('foreign board kit')
    entries={l.split('  ',1)[1]:l[:64] for l in manifest.read_text().splitlines()}
    rtl=ROOT/'rtl/perf/vcu_lvt_regfile.v';tb=ROOT/'tests/lvt_regfile_tb.v';source=rtl.read_text();out.mkdir();out=out.resolve();results=[]
    tools=[str(iverilog)]+(['-B',str(ivl)] if ivl else []);version=subprocess.run([*tools,'-V'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True,text=True).stdout.splitlines()[0]
    for d,r,w,ref,parent in PROFILES:
        f=kit/f'rtl/regfile_128x{d}.sv';par=kit/f'rtl/{parent}.sv'
        if digest(f)!=ref or any(digest(p)!=entries.get(p.relative_to(kit).as_posix()) for p in (f,par)):
            raise ValueError('foreign generated RAM or enclosing module')
        conns=par.read_text().split(f'regfile_128x{d} regfile_ext (')[1].split(');')[0]
        if set(re.findall(r'\.([RW]\d+)_clk\s*\(clock\)',conns))!={f'R{i}' for i in range(r)}|{f'W{i}' for i in range(w)}:raise ValueError('not a shared clock')
        p=out/f'ram{d}';p.mkdir();wrap=p/'reference_wrapper.v';wrap.write_text(wrapper(d,r,w))
        for neg in (False,True):
            # Reverse tag write order only. The original and independent scoreboard
            # keep highest-index priority and must catch this mutation at n=0.
            design=rtl if not neg else p/'wrong_priority.v'
            if neg:
                pattern='for (i=0; i<NW; i=i+1)';assert source.count(pattern)==1
                design.write_text(source.replace(pattern,'for (i=NW-1; i>=0; i=i-1)'))
            exe=p/('mutant.vvp' if neg else 'actual.vvp')
            subprocess.run([*tools,'-g2012','-s','tb',f'-DTEST_D={d}',f'-DTEST_R={r}',f'-DTEST_W={w}','-o',exe,f,wrap,design,tb],check=True)
            run=subprocess.run([str(vvp),'-N',*(['-M',str(ivl)] if ivl else []),exe],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
            (p/('negative.txt' if neg else 'positive.txt')).write_text(run.stdout)
            edges=128*(1<<w)+2048;checks=r*(2+128*(1<<w)*2+2048*3)
            marker=f'RF_COMPARE_PASS width={d} readers={r} writers={w} edges={edges} lane_checks={checks}'
            if neg:
                if run.returncode==0 or not re.search(r'RF_MISMATCH n=0 reader=0 edges=4\b',run.stdout) or 'RF_COMPARE_PASS' in run.stdout:raise ValueError('collision-priority control not rejected')
            elif run.returncode!=0 or run.stdout.splitlines().count(marker)!=1:raise ValueError('not all RAM comparisons passed: '+run.stdout[-400:])
        results.append(dict(data_bits=d,depth=128,read_ports=r,write_ports=w,reference_sha256=ref,enclosing_module_sha256=digest(par),edges=edges,read_lane_checks=checks,wrong_writer_priority_rejected=True))
    return dict(scope='Isolated four-state behavioral differential test of an alternative LVT register file, with default random-init macros off. No synthesis, routing, performance or full-core qualification.',board_input_seal=SEAL,candidate_sha256=digest(rtl),testbench_sha256=digest(tb),simulator=version,profiles=results)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--iverilog',default='iverilog');p.add_argument('--vvp',default='vvp');p.add_argument('--ivl',type=Path);a=p.parse_args();result=review(a.kit.resolve(),a.out,a.iverilog,a.vvp,a.ivl);(a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('TWO_RAM_DIFFERENTIALS_PASSED_NOT_TIMING')
