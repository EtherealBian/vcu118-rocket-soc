#!/usr/bin/env python3
"""Check two F3 candidates in their real BoomFrontend parent, with cut inputs driven."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import runpy
import subprocess

M=runpy.run_path(str(Path(__file__).with_name('test-mega-f3-history-compare.py')))
check=M['check']; Q=M['Q']; F=M['F']; H=M['H']; FLAGS=M['FLAGS']; CORR=M['CORR']

def tb():
    # The final PC mux is real. Hold the earlier-stage alternative to S2's PC;
    # the SFENCE and external redirect inputs are also independently exercised.
    extra={'_GEN_31':1,'io_cpu_sfence_bits_addr':39,'io_cpu_redirect_pc':40}
    inputs={**M['INPUT'],**extra}; outputs={**M['OUTPUT'],'s0_vpc':40}
    width=lambda w: f'[{w-1}:0] ' if w>1 else ''
    rows=['`timescale 1ps/1ps','module tb;', 'reg [31:0] rng=32\'h45abc177;',
          'function automatic [31:0] word; reg [31:0] x; begin x=rng; x=x^(x<<13); x=x^(x>>17); x=x^(x<<5); rng=x; word=x; end endfunction',
          'integer t,i,j,b,neg=0,pc_f3=0,pc_s2=0,exact1=0,exact2=0;', 'reg [63:0] bit1=0,bit2=0; reg [7:0] lanes=0,ends=0;',
          *['reg '+width(w)+'x_'+n+';' for n,w in inputs.items()]]
    variants={'gold':'BoomFrontend','fast':'PrefixFrontend','lean':'LanesFrontend','fault':'BadFrontend'}
    for inst,mod in variants.items():
        rows.extend([mod+' '+inst+'(.clock(1\'b0),.reset(1\'b0));','wire [121:0] out_'+inst+'={'+','.join(inst+'.'+n for n in outputs)+'};'])
    check(sum(outputs.values())==122,'unexpected readout')
    rows+=['initial begin']
    for n in inputs:
        rows.extend(f'force {inst}.{n} = x_{n};' for inst in variants)
    rows+=['for(t=0;t<3072;t=t+1) begin']
    for n,w in inputs.items():
        rows.append('x_'+n+' = {'+', '.join('word()' for _ in range((w+31)//32))+'};')
    rows.extend(['x__GEN_31=1; x_io_cpu_sfence_valid=(t%31==0); x_io_cpu_redirect_flush=(t%29==0);',
                 'x__f3_io_deq_valid=1; x__f4_io_enq_ready=(t%19!=0); x__f3_io_deq_bits_pc[5:3]=t%8;',
                 'x_s1_valid=(t%7!=0); x_s2_valid=(t%3!=0); if(t%4!=0) x_s1_vpc=x_f3_predicted_target; if(t%5!=0) x_s2_vpc=x_f3_predicted_target;',
                 'if ((t%4)==0) begin x_f3_prev_is_half=0; x__f3_io_deq_bits_data=0; x__f3_io_deq_bits_mask=8\'hff;'])
    # A single real conditional branch in each of the 8 lanes. Decoder ports
    # for the two alternate half-instructions at a bank edge get the same type.
    lane=[0,0,1,2,3,4,4,5,6,7]
    for n,k in zip(M['CFI'],lane): rows.append(f'x_{n}=((t/4)%8=={k}) ? 1 : 0;')
    for n in M['PRED']: rows.append(f'x_{n}=1;')
    rows+=['end', '#3;']
    for stage in (1,2):
        sp=f's{stage}_ghist_'; rows.extend(f'x_{sp+n}=gold.{F+n};' for n in (H,*FLAGS))
        rows.append(f'if ((t+{stage})%4==0 || (t>=2048 && t<2112)) begin x_{sp+H}=x_{sp+H} ^ (64\'b1 << (t%64)); bit{stage}[t%64]=1; end')
    rows+=['#3;', 'if ((^out_gold)===1\'bx || out_gold!==out_fast || out_gold!==out_lean) $fatal(1,"parent mismatch/unknown t=%0d",t);',
           'if ((^out_fault)===1\'bx) $fatal(1,"unknown negative readout"); if(out_fault!=out_gold) neg=neg+1;',
           'if(gold.f4_io_enq_bits_cfi_idx_valid) lanes[gold.f4_io_enq_bits_cfi_idx_bits]=1; ends[x__f3_io_deq_bits_pc[5:3]]=1;',
           'if(gold.'+CORR[0]+') exact1=exact1+1; if(gold.'+CORR[1]+') exact2=exact2+1;',
           'if(!x_io_cpu_redirect_flush && !x_io_cpu_sfence_valid && x_s2_vpc!=x_f3_predicted_target) begin',
           'if(gold._GEN_133 && gold.s0_vpc==x_s2_vpc) pc_s2=pc_s2+1; else if(!gold._GEN_133 && gold.s0_vpc==x_f3_predicted_target) pc_f3=pc_f3+1; else $fatal(1,"wrong PC consumer"); end',
           'end', 'if(neg<8 || pc_s2<5 || pc_f3<5 || !(&lanes) || !(&ends) || !(&bit1) || !(&bit2) || exact1<100 || exact2<100 || exact1>=3072 || exact2>=3072) $fatal(1,"missing coverage %d %d %d %h",neg,pc_f3,pc_s2,lanes);',
           '$display("HIST_PARENT samples=3072 mismatching_mutant=%0d pc_f3=%0d pc_s2=%0d exact_f1=%0d exact_f2=%0d lanes=%h pc_groups=%h flip1=%h flip2=%h",neg,pc_f3,pc_s2,exact1,exact2,lanes,ends,bit1,bit2); $finish;', 'end','endmodule','']
    return '\n'.join(rows)

def run(kit,proof,tools,out):
    check(all(out!=p and out not in p.parents and p not in out.parents for p in (kit,proof,tools)), 'output overlaps inputs'); out.mkdir()
    r=json.loads((proof/'result.json').read_bytes()); data=(kit/'rtl/BoomFrontend.sv').read_bytes(); h=lambda v:sha256(v).hexdigest()
    seal=(kit/'CANDIDATE.sha256').read_bytes();check(h(seal)==M['SEAL'] and h(data)==M['LEAF'],'wrong source')
    src=data.decode(); direct=M['prefix'](src);fast=M['derive'](direct);small=M['eligible_lanes'](direct)
    for n,v in [('prefix_and_compare',fast),('eligible_lanes',small)]:check(r['proofs'][n]=='equivalent' and r['derived_leaf_sha256'][n]==h(v.encode()) and (proof/(n+'-BoomFrontend.sv')).read_bytes()==v.encode(),'unmatched derived file')
    faulty=M['one'](small,'(f3_br_mask_2 & ~'+M['PRED'][2]+')','(_f3_br_mask_2_T & ~'+M['PRED'][2]+')')
    deps=sorted(set(re.findall(r'^  (\w+) \w+ \(',src,re.M))); check(len(deps)==13,'unexpected direct children'); headers=[]; dig={}
    for n in deps:
        raw=(kit/'rtl'/(n+'.sv')).read_bytes();dig[n]=h(raw);check((dig[n]+'  rtl/'+n+'.sv').encode() in seal.splitlines(), 'unsealed child')
        header=re.findall(r'^module '+n+r'\(.*?^\);',raw.decode(),re.M|re.S);check(len(header)==1,'unrecognized interface '+n);headers.append(header[0]+'\nendmodule\n')
    files={'children.sv':'\n'.join(headers),'tb.sv':tb(),'gold.sv':src}
    for name,v in [('PrefixFrontend',fast),('LanesFrontend',small),('BadFrontend',faulty)]:files[name+'.sv']=M['one'](v,'module BoomFrontend(', 'module '+name+'(')
    for n,v in files.items():(out/n).write_bytes(v.encode())
    def call(name,args):
        proc=subprocess.run([str(tools/'bin'/(name+('.bat' if os.name=='nt' else ''))),*args],cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180);(out/(name+'-stdout.log')).write_bytes(proc.stdout);text=proc.stdout.decode(errors='replace');check(proc.returncode==0 and not re.search(r'(?im)^\s*(error:|fatal:)',text),name+' failed');return text
    call('xvlog',['--sv','-d','SYNTHESIS',*files]);log=call('xelab',['tb','--mt','off','--timescale','1ps/1ps','-s','parent']);check('Vivado Simulator v2024.2' in log and 'Built simulation snapshot parent' in log,'wrong version')
    log=call('xsim',['parent','--runall']); m=re.findall(r'^HIST_PARENT samples=3072 mismatching_mutant=(\d+) pc_f3=(\d+) pc_s2=(\d+) exact_f1=(\d+) exact_f2=(\d+) lanes=ff pc_groups=ff flip1=f{16} flip2=f{16}\s*$',log,re.M);check(len(m)==1 and '$finish called' in log,'incomplete run')
    return dict(scope='Known input differential samples on unextracted BoomFrontend RTL. Child interfaces are stubs, parent cut signals driven, clock held still, not a clocked fetch or boot test.',
                source_sha256=M['LEAF'],proof_sha256=h((proof/'result.json').read_bytes()),direct_child_inputs=dig,fixture_sha256=h(files['tb.sv'].encode()),sampled_output_bits=122,
                samples=3072,all_eight_pc_groups_and_taken_lanes=True,history_mismatch_bit_coverage_each_stage=64,
                **dict(zip(('mutant_disagreements','f3_pc_selected_distinct','s2_pc_selected_distinct','exact_f1','exact_f2'),map(int,m[0]))))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('kit','proof','vivado','out'): p.add_argument(n,type=Path)
    a=p.parse_args(); r=run(*(v.resolve() for v in (a.kit,a.proof,a.vivado,a.out)));(a.out/'result.json').write_bytes((json.dumps(r,indent=2)+'\n').encode());print(json.dumps(r,indent=2))
