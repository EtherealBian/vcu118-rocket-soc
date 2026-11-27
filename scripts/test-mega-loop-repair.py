#!/usr/bin/env python3
"""Whole four-column bank equivalence and directed lockstep of the F3 overlay."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess

D = runpy.run_path(str(Path(__file__).with_name('derive-mega-loop-repair.py')))
BANK, COL = D['BANK'], D['COL']


def need(ok, text):
    if not ok:
        raise ValueError(text)


def yosys_column(text):
    # Yosys 0.9 cannot parse multidimensional packed nets. The entire 16-row
    # RHS stays identical; make its word ordering explicit in the concat LHS.
    def split(m):
        width, name, rhs = m.groups()
        return (f'wire [{width}:0] {name} [15:0];\n  assign {{'+
                ','.join(f'{name}[{i}]' for i in reversed(range(16)))+'} = '+rhs+';')
    text, n = re.subn(r'wire \[15:0\]\[([29]):0\] (_GEN(?:_[0-3])?) = ([^;\n]+);', split, text)
    need(n == 5 and '[15:0][' not in text, 'unrecognized packed table')
    return text


def make_files(out, sources):
    out.mkdir()
    for version, files in sources.items():
        d = out/version
        d.mkdir()
        for n, text in files.items():
            (d/(n+'.sv')).write_bytes(text.encode())
        (d/'column.for-yosys.v').write_bytes(yosys_column(files[COL]).encode())


OLD = [f'columns_{i}.f3_scnt_REG' for i in range(4)]
NEW = 'vcu_f3_repair_bypass'
CTRL = ['s1_update_valid','s1_update_bits_is_repair_update','s1_update_bits_br_mask','s1_update_idx']


def invoke(out, exe, script, stem):
    (out/(stem+'.ys')).write_text(script+'\n')
    with (out/(stem+'.log')).open('wb') as f:
        subprocess.run([exe,'-Q','-T','-s',stem+'.ys'], cwd=out, stdout=f,stderr=subprocess.STDOUT,timeout=360,check=True)
    return (out/(stem+'.log')).read_text()


def unwrap(out, exe, src):
    invoke(out,exe,f'read_verilog -sv -noautowire {src}/column.for-yosys.v {src}/{BANK}.sv\nhierarchy -check -top {BANK}; proc; flatten; memory_map; opt_clean; check -assert; write_json {src}/flat.json',src+'/lower')
    mod = json.loads((out/src/'flat.json').read_bytes())['modules'][BANK]
    need(not mod.get('memories') and not mod.get('processes'), 'unlowered state')
    ports = mod['ports'].copy()
    aliases = {}
    for name, net in mod['netnames'].items():
        if not net['hide_name']:
            aliases.setdefault(tuple(net['bits']),[]).append(name)
    regs = {}
    for ident, cell in list(mod['cells'].items()):
        if cell['type'] != '$dff':
            need(cell['type'] in {'$mux','$eq','$and','$or','$not','$pmux','$reduce_and','$reduce_or','$add','$ne','$sub','$xor'}, 'unknown state or unsupported logic')
            continue
        pins, param = cell['connections'], cell['parameters']
        need(pins['CLK']==ports['clock']['bits'] and int(str(param['CLK_POLARITY']),2)==1 and len(pins['Q'])==len(pins['D']), 'not a single positive clock')
        names = aliases[tuple(pins['Q'])]
        # Prefer directly named flops over column ports or packed table aliases.
        name = min(names,key=lambda n: ('.io_' in n or '._GEN' in n,len(n),n))
        need(name not in regs, 'duplicate flop name')
        regs[name] = (pins['Q'],pins['D'])
        del mod['cells'][ident]
    qbits = [x for q,_ in regs.values() for x in q]
    need(len(qbits)==len(set(qbits)) and all(isinstance(x,int) for x in qbits),'Q alias')
    return mod, regs, {k:(v['direction'],len(v['bits'])) for k,v in ports.items()}


def formal(out, exe, version, gold_flat, gate_flat):
    # Cut every flop, share each unchanged Q, compare every D. A distinct
    # current and next state relation covers the retimed enables (not a waiver).
    import copy
    gold, state0, ports = copy.deepcopy(gold_flat)
    gate, state1, p1 = copy.deepcopy(gate_flat)
    need(ports==p1 and (set(state0)-set(state1),set(state1)-set(state0))==(set(OLD),{NEW}), 'unmatched states or ports')
    common = sorted(set(state0)&set(state1))
    maps = [{},{}]; wires=[]; shared = {}; extra = [{},{}]
    def sig(n,w):
        wires.append(f'wire [{w-1}:0] {n};'); return n
    def port(m,n,bits,direction):
        need(n not in m['ports'] and n not in m['netnames'], 'port collision')
        m['ports'][n]={'direction':direction,'bits':bits}
        m['netnames'][n]={'hide_name':0,'bits':bits,'attributes':{}}
    primary = []; observes=[[],[]]; dvalues=[[],[]]
    for name,(direction,w) in ports.items():
        if direction=='input':
            primary.append(f'input [{w-1}:0] i_{name}'); maps[0][name]=maps[1][name]='i_'+name
        else:
            for j in (0,1):
                maps[j][name]=sig(f'o{j}_{name}',w); observes[j].append(maps[j][name])
    for i,name in enumerate(common):
        w=len(state0[name][0]); need(len(state1[name][0])==w,'mismatched register width')
        q=f'q_{i}'; primary.append(f'input [{w-1}:0] {q}'); shared[name]=q
        for j,(m,regs) in enumerate([(gold,state0),(gate,state1)]):
            qb,db=regs[name]; port(m,q,qb,'input'); maps[j][q]=q
            dp='d_'+str(i); port(m,dp,db,'output'); dn=sig(f'd{j}_{i}',w); maps[j][dp]=dn; dvalues[j].append(dn);extra[j][name]=dn
    for i,name in enumerate(OLD):
        qb,db=state0[name]; need(len(qb)==36,'wrong index width'); nq=f'old_idx_{i}'; primary.append(f'input [35:0] {nq}'); shared[name]=nq
        nd=f'next_idx_{i}';port(gold,nq,qb,'input');port(gold,nd,db,'output');maps[0][nq]=nq;maps[0][nd]=sig(nd,36);extra[0][name]=nd
    def relation(s):
        v,r,mask,idx=[s[n] for n in CTRL]
        return '{'+', '.join(f'({v} & {r} & {mask}[{i}] & ({idx} == {s[OLD[i]]}))' for i in reversed(range(4)))+'}'
    qb,db=state1[NEW];need(len(qb)==4,'wrong enable width');port(gate,'current_enable',qb,'input');port(gate,'next_enable',db,'output');maps[1].update(current_enable=relation(shared),next_enable=sig('next_enable',4))
    join=lambda vs: '{'+','.join(vs)+'}'
    # Compare large shared vectors per word, not by sampling one bit per word.
    checks = ['('+join(observes[0])+' == '+join(observes[1])+')',
              '('+join(dvalues[0])+' == '+join(dvalues[1])+')', '(next_enable == '+relation(extra[0])+')']
    top=['module relation('+', '.join(primary+['output ok'])+');']+wires
    for j,(m,nn) in enumerate([(gold,'orig'),(gate,'alt')]):
        (out/version/(nn+'.json')).write_text(json.dumps({'modules':{nn:m}}))
        top.append(f'{nn} u{j}('+','.join(f'.{k}({val})' for k,val in maps[j].items())+');')
    top+=['assign ok = '+' & '.join(checks)+';','endmodule']
    (out/version/'relation.v').write_text('\n'.join(top)+'\n')
    log=invoke(out,exe,f'read_json {version}/orig.json; read_json {version}/alt.json; read_verilog -noautowire {version}/relation.v\nhierarchy -check -top relation; proc; flatten; opt; check -assert; sat -prove ok 1 relation',version+'/step')
    success='SAT proof finished - no model found: SUCCESS!'; failed='SAT proof finished - model found: FAIL!'
    need(log.count(success)==int(version=='candidate') and log.count(failed)==int(version!='candidate'),'unexpected SAT decision')
    return dict(common_registers=len(common),common_state_bits=sum(len(state0[n][0]) for n in common),replaced_reference_index_bits=144,retimed_enable_bits=4,output_bits=sum(w for d,w in ports.values() if d=='output'),decision='equivalent_step' if version=='candidate' else 'counterexample')


def testbench(text):
    src = re.sub(r'//[^\n]*','',text)
    pins = re.findall(r'^  (input|output)\s+(?:\[(\d+):0\]\s+)?(\w+),?\s*$',src,re.M)
    ins=[(n,int(w or 0)+1) for d,w,n in pins if d=='input']; outs=[n for d,w,n in pins if d=='output']
    need(len(ins)==73 and len(outs)==61 and sum(w for _,w in ins)==744,'wrong bank interface')
    body=['module tb;', 'integer t,seed,hit,stalls,train,overlaps; reg [35:0] pc1,pc2,delta,missed; reg [15:0] masks; reg [3:0] flipped,expect_en;',
          *[f'reg [{w-1}:0] {n};' for n,w in ins]]
    links=','.join(f'.{n}({n})' for n,_ in ins)
    body += [f'{BANK} g({links}); CandidateBank c({links});',
             'wire [647:0] g_obs={'+','.join('g.'+n for n in outs)+'};',
             'wire [647:0] c_obs={'+','.join('c.'+n for n in outs)+'};',
             '''task compare; begin
if (^g_obs === 1'bx) begin $display("LOOP_UNKNOWN_REFERENCE t=%0d",t); $finish_and_return(3); end
if (g_obs !== c_obs) begin $display("LOOP_OUTPUT_MISMATCH t=%0d",t); $finish_and_return(2); end
end endtask
initial begin clock=0; seed=32'h51d0f33; pc1=0; pc2=0; missed=0; masks=0; hit=0; stalls=0; train=0; overlaps=0; flipped=0;
for(t=0;t<2304;t=t+1) begin''']
    for n,w in ins:
        if n!='clock': body.append(n+'={'+','.join('$random(seed)' for _ in range((w+31)//32))+'};')
    body += ['''reset=(t<2 || t==1099); io_update_bits_pc={pc2,io_f0_pc[3:0]};
if(t%64<52) begin
 io_update_valid=1; io_update_bits_is_repair_update=1;
 if(t%64<16) io_update_bits_br_mask=t%16;
 else begin delta=36'b1 << (t%64-16); io_update_bits_pc[39:4]=pc2 ^ delta; io_update_bits_br_mask=15; end
end
// Train all four lanes at one index with equal observed & predicted trip counts.
if(t>=128 && t<320) begin
 io_f0_pc=40'h1234500120; io_update_bits_pc=io_f0_pc; io_f0_mask=15; io_f0_valid=1;
 io_f3_fire=0; io_update_valid=1; io_update_bits_br_mask=15;
 io_update_bits_is_mispredict_update=1; io_update_bits_cfi_mispredicted=1;
 io_update_bits_is_repair_update=1; io_update_bits_meta={12{10'd3}};
end
#2; if(t>24) compare;
expect_en={4{io_update_valid & io_update_bits_is_repair_update & (pc2==io_update_bits_pc[39:4])}} & io_update_bits_br_mask;
delta=pc2 ^ io_update_bits_pc[39:4]; pc2=pc1; pc1=io_f0_pc[39:4];
clock=1; #2;
if(t>24) begin
 compare; if(c.vcu_f3_repair_bypass !== expect_en) $fatal(1,"BYPASS_MISMATCH %0d",t);
 if(io_update_valid && io_update_bits_is_repair_update) begin
  if(delta==0) begin hit=hit+1; masks[io_update_bits_br_mask]=1; end
  else if((delta & (delta-36'd1))==0 && io_update_bits_br_mask==15) missed=missed | delta;
  if(io_update_bits_is_mispredict_update && io_update_bits_cfi_mispredicted && io_update_bits_br_mask!=0) overlaps=overlaps+1;
 end
 if(!io_f3_fire && expect_en!=0) stalls=stalls+1;''']
    for i in range(4):
        body += [f'if(g.io_resp_f3_{i}_taken != io_resp_in_0_f3_{i}_taken) begin flipped[{i}]=1; train=train+1; end']
    body += ['''end
clock=0; #1; end
if(masks!==16'hffff || missed!=={36{1'b1}} || flipped!==4'hf || hit<100 || stalls<50 || overlaps<30) $fatal(1,"MISSING_COVERAGE masks=%h bits=%h flipped=%h hit=%d stalls=%d overlaps=%d",masks,missed,flipped,hit,stalls,overlaps);
$display("LOOP_LOCKSTEP_OK hits=%0d fire_low_hits=%0d overlapping_updates=%0d flipped_lane_samples=%0d",hit,stalls,overlaps,train); $finish; end endmodule''']
    return '\n'.join(body)+'\n'


def simulation(out, ivl, vvp, lib, version):
    d=out/version
    col=(d/(COL+'.sv')).read_text(); rewritten=(d/(BANK+'.sv')).read_text().replace('module '+BANK+'(','module CandidateBank(')
    need(rewritten.count(COL+' columns_')==4,'need all columns')
    (d/'sim-candidate.sv').write_text(col.replace('module '+COL+'(','module CandidateCol(')+'\n'+rewritten.replace(COL+' columns_', 'CandidateCol columns_'))
    compiled=subprocess.run([ivl,'-B',lib,'-g2012','-s','tb','-o','pair','../stock/'+COL+'.sv','../stock/'+BANK+'.sv','sim-candidate.sv','../tb.sv'],cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
    (d/'compile.log').write_text(compiled.stdout); need(compiled.returncode==0,'compile failed: '+compiled.stdout[-200:])
    proc=subprocess.run([vvp,'-M',lib,'pair'],cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
    (d/'sim.log').write_text(proc.stdout)
    if version!='candidate':
        need(proc.returncode==2 and re.search(r'^LOOP_OUTPUT_MISMATCH t=\d+$',proc.stdout,re.M),'negative control did not change observable output: '+proc.stdout[-200:]); return 'output_mismatch'
    found=re.findall(r'^LOOP_LOCKSTEP_OK hits=(\d+) fire_low_hits=(\d+) overlapping_updates=(\d+) flipped_lane_samples=(\d+)$',proc.stdout,re.M)
    need(proc.returncode==0 and len(found)==1 and 'FATAL' not in proc.stdout, 'incomplete lockstep: '+proc.stdout[-240:]);return dict(zip(['address_match_repair_cycles','f3_fire_low_with_enabled_bypass','overlapping_repair_and_mispredict_updates','flipped_prediction_lane_samples'],map(int,found[0])))


def run(kit,out,yosys,ivl,vvp,lib):
    orig=D['sealed'](kit); alt=D['derive'](orig); bad=alt.copy()
    bad[BANK]=D['once'](bad[BANK],'(s2_idx == io_update_bits_pc[39:4])','(s2_idx[34:0] == io_update_bits_pc[38:4])')
    versions={'stock':orig,'candidate':alt,'ignore_bit35':bad}
    make_files(out,versions); bench=testbench(orig[BANK]); (out/'tb.sv').write_text(bench)
    gold_flat=unwrap(out,yosys,'stock'); formal_runs={}; sims={}
    for v in ('candidate','ignore_bit35'):
        formal_runs[v]=formal(out,yosys,v,gold_flat,unwrap(out,yosys,v));sims[v]=simulation(out,ivl,vvp,lib,v)
    digest=lambda b: sha256(b).hexdigest()
    result=dict(scope='One full four-column bank. Two-state inductive state relation checked from every related state for every input; all-zero storage satisfies the relation. Four-state finite post-reset lockstep uses the original packed RTL. No routed candidate, frequency or board score.',kit_sha256=D['KIT'],source_sha256=D['HASHES'],candidate_sha256={n:digest(txt.encode()) for n,txt in alt.items()},formal=formal_runs,lockstep=sims,clock_edges=2304,first_compared_edge=26,tool_sha256={p.name:digest(p.read_bytes()) for p in [yosys,ivl,vvp,lib/'ivl',lib/'ivlpp',lib/'vvp.tgt']},bench_sha256=digest(bench.encode()))
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n'); print('LOOP_BANK_RELATION_AND_LOCKSTEP_COMPLETE')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('fresh_out',type=Path)
    for arg in ('yosys','iverilog','vvp','ivl-dir'):p.add_argument('--'+arg,required=True,type=Path)
    a=p.parse_args();run(a.kit.resolve(),a.fresh_out.resolve(),a.yosys.resolve(),a.iverilog.resolve(),a.vvp.resolve(),a.ivl_dir.resolve())
