#!/usr/bin/env python3
"""Explore a dual-port MSHR way-select retiming on an isolated four-wide module.

Does not modify the implementation kit, its constraints, or the running Vivado
process. The generated module is a private what-if, not new implementation RTL.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
C = runpy.run_path(str(HERE/'check-mshr-way-cone.py'))
NAME = C['MODULE']
MOD = 'rtl/'+NAME+'.sv'
SEAL = 'b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'
STOCK = 'fdd20681408038f71c070fc1e8776a43f4ba38af7d5814af6b8e5c61162031d2'

def transform(src):
    if sha256(src).hexdigest()!=STOCK: raise ValueError('unexpected four-wide D-cache')
    text=src.decode('ascii')
    def pick(pat):
        matches=list(re.finditer(pat,text,re.M))
        if len(matches)!=1: raise ValueError('ambiguous structural cut')
        return matches[0]
    idx=pick(r'^    s2_replaced_way_en_REG <= ([^;\n]+);')[1]
    for port in range(2):
        tag='s2_tag_match_way_'+str(port); reg='vcu_mshr_way_q_'+str(port); mask='vcu_mshr_mask_d_'+str(port)
        rhs=pick(r'^    '+tag+r' <= ([^;\n]+);')[1]; always=pick(r'^  always @\(posedge clock\) begin(?=\s*//|$)')
        text=text[:always.start()]+f'  wire [7:0] {mask} = {rhs};\n  reg [7:0] {reg};\n'+text[always.start():]
        # Add a parallel register. Leave every other consumer of the old signals untouched.
        cut=pick(r'^    '+tag+r' <= ');text=text[:cut.start()]+f"    {reg} <= (|{mask}) ? {mask} : (8'h1 << {idx});\n"+text[cut.start():]
        pin=pick(r'^(    \.io_req_'+str(port)+r'_bits_way_en\s+\()\(\|'+tag+r'\) \? '+tag+r' : s2_replaced_way_en(\),)')
        text=text[:pin.start()]+pin[1]+reg+pin[2]+text[pin.end():]
    return text.encode('ascii')

def review(kit,out,tool):
    kit=kit.resolve(strict=True); out=out.resolve(); version=subprocess.check_output([tool,'--version'],text=True).strip()
    if not version.startswith('Verilator 5.022 '): raise ValueError('require Verilator 5.022')
    if sha256((kit/'CANDIDATE.sha256').read_bytes()).hexdigest()!=SEAL: raise ValueError('wrong board implementation kit')
    seals=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals'](kit)
    names=(kit/'sources.f').read_text().splitlines()
    if len(names)!=549 or len(set(names))!=len(names) or names.count(MOD)!=1 or seals[MOD]!=STOCK: raise ValueError('wrong HDL order or module')
    out.mkdir(); source=out/(NAME+'.sv'); source.write_bytes(transform((kit/MOD).read_bytes()))
    xml=[]
    for label,module in [('stock',kit/MOD),('retimed',source)]:
        sub=out/label; sub.mkdir(); mf=sub/'inputs.f'; mf.write_text(''.join(str(module if n==MOD else kit/n)+'\n' for n in names)); tree=sub/'dcache.xml'
        with (sub/'parser.txt').open('wb') as f:
            subprocess.run([tool,'--xml-only','--xml-output',tree,'--Mdir',sub,'-DSYNTHESIS','--top-module',NAME,'-Wno-fatal','-f',mf],stdout=f,stderr=subprocess.STDOUT,check=True)
        xml.append(tree)
    results=[]; paired=[]
    for i in range(2):
        pin=f'io_req_{i}_bits_way_en'; tag='s2_tag_match_way_'+str(i); cones=[C['Cone'](x,pin=pin) for x in xml]
        results.append(dict(port=i,**C['check_cones'](*cones,tag_register=tag))); paired.append(cones)
    # Compare each output with the *opposite* candidate port. If an extraction lost
    # port identity the pair could pass despite swapping the two cache requests.
    for i in range(2):
        try: C['check_cones'](paired[i][0],paired[1-i][1],tag_register='s2_tag_match_way_'+str(i))
        except ValueError: pass
        else: raise ValueError('cross-port substitution was not rejected')
    return dict(scope='RTL experiment on the two D-cache MSHR request ports, one-edge two-state comparison for each port using its own tag mask and the common replacement index. No whole-SoC equivalence, reset proof, timing, bitstream or physical score.',implementation_kit_seal=SEAL,reference_module_sha256=STOCK,candidate_module_sha256=sha256(source.read_bytes()).hexdigest(),other_ordered_hdl_sources_unchanged=len(names)-1,parser=version,cross_port_substitutions_rejected=2,ports=results)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--verilator',default='verilator');a=p.parse_args(); result=review(a.kit,a.out,a.verilator); (a.out/'proof.json').write_text(json.dumps(result,indent=2)+'\n');print('MEGA_TWO_PORT_CONE_CHECKED_NOT_TIMING')
