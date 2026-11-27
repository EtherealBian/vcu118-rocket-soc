#!/usr/bin/env python3
"""Prepare a separate, unqualified four-wide board input for a register-file experiment.

The currently implementing input, original XDC, clock request, boot ROM, CPU
parents, and physical shell are never modified. No synthesis or hardware access.
"""
from pathlib import Path
import argparse
import json
import re
import runpy
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
rf = runpy.run_path(str(HERE/'check-mega-regfile.py'))
sealed = runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']
LEAF = 'rtl/vcu_lvt_regfile.v'
DUT = 'vcu_lvt_regfile #(.DATA(D),.ADDR(7),.NR(R),.NW(W)) proposed(clk,ra,re,candidate,wa,we,wd);'


def adapter(original, bits, readers, writers):
    name = f'regfile_128x{bits}'
    expected = []; connections = {'clock':'W0_clk'}
    for prefix, cnt in [('R',readers),('W',writers)]:
        for i in range(cnt):
            for suffix, width in [('addr',7),('en',1),('clk',1),('data',bits)]:
                io = 'output' if prefix=='R' and suffix=='data' else 'input'
                expected.append((io, '' if width==1 else f'[{width-1}:0]',f'{prefix}{i}_{suffix}'))
        for suffix in ('addr','en','data'):
            connections[prefix.lower()+suffix] = '{'+', '.join(f'{prefix}{i}_{suffix}' for i in reversed(range(cnt)))+'}'
    clean = re.sub(r'//[^\n]*','',original)
    hdr, = re.findall(r'\bmodule\s+'+name+r'\s*\((.*?)\);',clean,re.S)
    declared = [re.fullmatch(r'\s*(input|output)\s*(\[\d+:0\])?\s*(\w+)\s*',line) for line in hdr.split(',')]
    if any(v is None for v in declared) or [v.groups(default='') for v in declared] != expected:
        raise ValueError('not the reviewed scalar port interface')
    return ('// Alternative asynchronous RAM leaf. Generated from the checked port contract.\n'
            'module '+name+'(\n  '+',\n  '.join(' '.join(filter(None,v)) for v in expected)+'\n);\n'
            f'  vcu_lvt_regfile #(.DATA({bits}),.ADDR(7),.NR({readers}),.NW({writers})) storage (\n    '+
            ',\n    '.join(f'.{k}({v})' for k,v in connections.items())+'\n  );\nendmodule\n')


def differential(kit, derived, out, d, r, w, compiler, runtime):
    directory=out/f'check-{d}'; directory.mkdir(); name=f'regfile_128x{d}'
    # Rename only the independent stock RAM and its instance. The candidate side
    # consumes the real derived flat-port wrapper, unchanged, including lane order.
    stock=(kit/f'rtl/{name}.sv').read_text(); decl='module '+name+'('; assert stock.count(decl)==1
    (directory/'stock.sv').write_bytes(stock.replace(decl,'module original_'+name+'(').encode())
    bridge=rf['wrapper'](d,r,w)
    (directory/'reference.v').write_bytes(bridge.replace(name+' dut','original_'+name+' dut').encode())
    (directory/'candidate.v').write_bytes(bridge.replace('module reference_wrapper','module derived_adapter').encode())
    bench=(HERE.parent/'tests/lvt_regfile_tb.v').read_text(); assert bench.count(DUT)==1
    (directory/'compare.v').write_bytes(bench.replace(DUT,'derived_adapter proposed(clk,ra,re,candidate,wa,we,wd);').encode())
    sources=['stock.sv','reference.v','candidate.v','compare.v',str(derived/LEAF)]
    for mutate in (False, True):
        ram=derived/f'rtl/{name}.sv'
        if mutate:
            text=ram.read_text(); a='R1_addr, R0_addr'; assert text.count(a)==1
            ram=directory/'wrong_read_order.v'; ram.write_bytes(text.replace(a,'R0_addr, R1_addr').encode())
        exe=('wrong' if mutate else 'real')+'.vvp'
        subprocess.run([*compiler,'-g2012','-s','tb',f'-DTEST_D={d}',f'-DTEST_R={r}',f'-DTEST_W={w}','-o',exe,*sources,str(ram)],cwd=directory,check=True)
        run=subprocess.run([*runtime,exe],cwd=directory,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=100)
        (directory/(exe+'.txt')).write_bytes(run.stdout.encode()); edges=128*(1<<w)+2048; checks=r*(2+128*(1<<w)*2+2048*3)
        expected=f'RF_COMPARE_PASS width={d} readers={r} writers={w} edges={edges} lane_checks={checks}'
        if mutate:
            if run.returncode==0 or not re.search(r'^RF_MISMATCH n=\d+ reader=[01] edges=\d+$',run.stdout,re.M) or 'RF_COMPARE_PASS' in run.stdout:
                raise ValueError('wrong read-lane order was not rejected')
        elif run.returncode!=0 or run.stdout.splitlines().count(expected)!=1:
            raise ValueError('derived leaf did not agree with original RAM')
    return dict(width=d,observed_clock_edges=edges,read_lane_checks=checks,swapped_read_addresses_rejected=True)


def derive(kit,out,iverilog,vvp,ivl):
    if kit==out or kit in out.parents or out.exists(): raise ValueError('need fresh output outside input tree')
    dig=rf['digest']; mf='CANDIDATE.sha256'
    if dig(kit/mf)!=rf['SEAL']: raise ValueError('wrong physical source seal')
    old=sealed(kit); src=(kit/'sources.f').read_bytes(); orig=src.decode().splitlines()
    if len(orig)!=549 or len(set(orig))!=549 or LEAF in old or src!=(''.join(n+'\n' for n in orig)).encode(): raise ValueError('unexpected ordered source list')
    out.mkdir(); dest=out/'candidate'; shutil.copytree(kit,dest)
    shutil.copyfile(HERE.parent/LEAF.replace('rtl/','rtl/perf/',1),dest/LEAF)
    (dest/'sources.f').write_bytes(src+LEAF.encode()+b'\n'); checks=[]; change=['sources.f',LEAF]
    compiler=[iverilog]+(['-B',str(ivl)] if ivl else []);runtime=[vvp,'-N']+(['-M',str(ivl)] if ivl else [])
    for d,r,w,h,parent in rf['PROFILES']:
        name=f'rtl/regfile_128x{d}.sv'; assert old[name]==h and orig.count(name)==1 and orig.count('rtl/'+parent+'.sv')==1
        (dest/name).write_bytes(adapter((kit/name).read_text(),d,r,w).encode()); change.append(name)
        checks.append(differential(kit,dest,out,d,r,w,compiler,runtime))
    sums={n:dig(dest/n) for n in set(old)|{LEAF}}
    if set(change)!={n for n in sums if sums[n]!=old.get(n)} or dig(kit/mf)!=rf['SEAL']:raise ValueError('unexpected derived delta')
    (dest/mf).write_bytes(''.join(f'{h}  {n}\n' for n,h in sorted(sums.items())).encode())
    if sealed(dest)!=sums: raise ValueError('unsealed extra or changed file')
    return dict(scope='Separate experimental four-wide source package. Differential checks include the flat memory port adapters. No coupled CPU simulation, Vivado implementation or physical score.',stock_board_seal=rf['SEAL'],candidate_board_input_seal=dig(dest/mf),original_ordered_hdl_files=len(orig),candidate_ordered_hdl_files=len(orig)+1,changed_or_added={n:sums[n] for n in sorted(change)},tests=checks)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--iverilog',default='iverilog');p.add_argument('--vvp',default='vvp');p.add_argument('--ivl',type=Path);a=p.parse_args()
    result=derive(a.kit.resolve(),a.out.resolve(),a.iverilog,a.vvp,a.ivl);(a.out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('SEPARATE_LVT_SOURCE_INPUT_READY_NOT_IMPLEMENTED')
