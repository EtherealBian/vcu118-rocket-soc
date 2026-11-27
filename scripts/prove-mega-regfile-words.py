#!/usr/bin/env python3
"""Prove the write/hold/read laws for the two sealed BOOM register files.

Uses Yosys' actual RTL-to-SMT transition relation (including the adapter),
not a handwritten model of the RTL. No Vivado or hardware access.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
RF=runpy.run_path(str(HERE/'check-mega-regfile.py'))
SEALS=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']


def digest(p):return sha256(p.read_bytes()).hexdigest()


def obligations(role, bits, readers, writers):
    """No model of next-state data here: T, arrays and primary I/O come from the DUT."""
    if role not in ('ref','alt') or bits not in (64,65) or (readers,writers)!=({64:(12,6),65:(6,4)}[bits]):raise ValueError('unknown interface')
    alt=role=='alt';tw=(writers-1).bit_length()
    def port(n,s):return f'(|dut_n {n}| {s})'
    def at(n,s):return f'(select (|dut_m {n}| {s}) q)'
    def bank(i,s):return at(f'storage.writer[{i}].bank',s)
    def tag(i,s):return f'(= {at("storage.owner",s)} (_ bv{i} {tw}))'
    states='(declare-const q (_ BitVec 7))\n(declare-const a |dut_s|)\n(declare-const b |dut_s|)\n'
    for i in range(writers):states+=f'(define-fun hit{i} () Bool (and {port(f"W{i}_en","a")} (= q {port(f"W{i}_addr","a")})))\n'
    hier='(|dut_h| a)';edge=[hier,'(|dut_h| b)','(|dut_t| a b)'];queries={}
    # No write to q: even invalid power-up tags and unselected banks must hold.
    names=(['storage.owner']+[f'storage.writer[{i}].bank' for i in range(writers)]) if alt else ['Memory']
    keep='(and '+' '.join(f'(= {at(n,"a")} {at(n,"b")})' for n in names)+')'
    queries['hold']=([*edge,*[f'(not hit{i})' for i in range(writers)]],keep)
    # Partition all other writes by their highest matching flat-memory port. All
    # lower writers and all nonmatching addresses/data remain unconstrained.
    for w in range(writers):
        value=bank(w,'b') if alt else at('Memory','b');eq=f'(= {value} {port(f"W{w}_data","a")})'
        queries[f'write{w}']=([*edge,f'hit{w}',*[f'(not hit{i})' for i in range(w+1,writers)]],f'(and {tag(w,"b")} {eq})' if alt else eq)
    # Enabled asynchronous read in one unrestricted state, no clock edge.
    # An LVT owner is valid after the first write and remains valid by induction.
    for r in range(readers):
        active=[hier,port(f'R{r}_en','a'),f'(= q {port(f"R{r}_addr","a")})'];out=port(f'R{r}_data','a')
        if alt:
            for w in range(writers):queries[f'read{r}_bank{w}']=([*active,tag(w,'a')],f'(= {out} {bank(w,"a")})')
        else:queries[f'read{r}']=(active,f'(= {out} {at("Memory","a")})')
    return states,queries


def check_answers(text,names,negative):
    expected=[]
    for name in names:expected.extend([name,'sat','sat' if negative else 'unsat'])
    actual=text.splitlines()
    if actual!=expected:
        j=next((i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b),min(len(actual),len(expected)))
        where=names[min(j//3,len(names)-1)]
        raise ValueError(f'{where}: missing result, unsatisfiable premise, failed property or solver error; inspect law.log')


def mutate(buf,old,new):
    if buf.count(old)!=1:raise ValueError('mutation does not match exactly once')
    return buf.replace(old,new)


def parent_lanes(text, bits, readers, writers):
    mod=f'regfile_128x{bits} regfile_ext ('
    if text.count(mod)!=1:raise ValueError('missing or duplicated storage instance')
    par=text.split(mod)[1].split(');')[0]
    clocks=re.findall(r'\.([RW]\d+)_clk\s*\(clock\)',par)
    if sorted(clocks)!=sorted([f'R{i}' for i in range(readers)]+[f'W{i}' for i in range(writers)]):
        raise ValueError('different enclosing clocks')
    mapping=[]
    for i in range(writers):
        found=[]
        for leaf,outer in [('addr','bits_addr'),('en','valid'),('data','bits_data')]:
            names=re.findall(rf'\.W{i}_{leaf}\s*\(io_write_ports_(\d+)_{outer}\)',par)
            if len(names)!=1:raise ValueError('missing or ambiguous parent write pin')
            found.append(int(names[0]))
        if len(set(found))!=1:raise ValueError('address/enable/data from different parent writers')
        mapping.append(found[0])
    if mapping!=list(reversed(range(writers))):raise ValueError('wrong parent writer order')
    return mapping


def solve(stock,lvt,out,yosys,z3):
    ref=json.loads((HERE.parent/'docs/perf-mega175-regfile-input.json').read_bytes())
    a,b=SEALS(stock),SEALS(lvt);mf='CANDIDATE.sha256'
    if (digest(stock/mf)!=ref['stock_board_seal'] or digest(lvt/mf)!=ref['candidate_board_input_seal'] or not set(a)<=set(b) or
        {n:h for n,h in b.items() if a.get(n)!=h}!=ref['changed_or_added']):raise ValueError('foreign or modified kits')
    if out.exists() or any(out==k or k in out.parents or out in k.parents for k in (stock,lvt)):raise ValueError('fresh directory outside both kits required')
    out.mkdir();cases={};parents={}
    for bits,r,w,rsha,parent in RF['PROFILES']:
        lname=f'regfile_128x{bits}.sv'; rtl='rtl/'+lname
        if rsha!=a[rtl]:raise ValueError('foreign reference')
        parents[str(bits)]=parent_lanes((stock/'rtl'/(parent+'.sv')).read_text(),bits,r,w)
        for mode in ('ref','alt','wrong_priority','wrong_bank_data','wrong_read_lane','stray_write'):
            role='ref' if mode=='ref' else 'alt';bad=mode not in ('ref','alt');name=f'{bits}-{mode}';d=out/name;d.mkdir()
            kit=stock if role=='ref' else lvt
            src=['vcu_lvt_regfile.v',lname] if role=='alt' else [lname]
            for n in src:shutil.copyfile(kit/'rtl'/n,d/n)
            ctrl={'wrong_priority':('vcu_lvt_regfile.v',b'for (i=0; i<NW; i=i+1)',b'for (i=NW-1; i>=0; i=i-1)',f'write{w-1}'),
                  'wrong_bank_data':('vcu_lvt_regfile.v',b'<= wdata[w*DATA+:DATA]',b'<= wdata[((w+1)%NW)*DATA+:DATA]',f'write{w-1}'),
                  'wrong_read_lane':(lname,b'R1_addr, R0_addr',b'R0_addr, R1_addr','read0_bank0'),
                  'stray_write':('vcu_lvt_regfile.v',b'if (wen[i]) owner[',b"if (1'b1) owner[",'hold')}
            if bad:
                f,old,new,only=ctrl[mode];f=d/f;f.write_bytes(mutate(f.read_bytes(),old,new))
            top=lname[:-3];cmd=('read_verilog -sv '+' '.join(src)+f'; hierarchy -check -top {top}; proc; flatten; opt; memory -nomap -nordff; opt; rename {top} dut; write_smt2 dut.smt2')
            with (d/'lower.log').open('wb') as log:subprocess.run([yosys,'-Q','-T','-p',cmd],cwd=d,stdout=log,stderr=subprocess.STDOUT,timeout=60,check=True)
            model=(d/'dut.smt2').read_text(); memories=[f'Memory 7 {bits} {r} {w} sync'] if role=='ref' else [f'storage.owner 7 {(w-1).bit_length()} {r} {w} sync',*[f'storage.writer[{i}].bank 7 {bits} {r} 1 sync' for i in range(w)]]
            if sorted(re.findall(r'^; yosys-smt2-memory (.+)$',model,re.M))!=sorted(memories) or re.findall(r'^; yosys-smt2-module (.+)$',model,re.M)!=['dut'] or re.search(r'^; yosys-smt2-(?:assume|assert|cell) ',model,re.M):raise ValueError('unexpected memory shape, hierarchy or embedded safety assumptions')
            states,queries=obligations(role,bits,r,w); names=[only] if bad else list(queries);query='(set-logic QF_AUFBV)\n(set-option :timeout 20000)\n'+model+states
            for k in names:
                pres,prop=queries[k];query+=f'(echo "{k}")\n(push)\n'+''.join(f'(assert {p})\n' for p in pres)+f'(check-sat)\n(assert (not {prop}))\n(check-sat)\n(pop)\n'
            job=d/'law.smt2';job.write_bytes(query.encode());run=subprocess.run([z3,'-memory:512','law.smt2'],cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300);(d/'law.log').write_bytes(run.stdout);run.check_returncode();check_answers(run.stdout.decode(),names,bad)
            cases[name]=dict(laws=names,antecedents_satisfiable=len(names),counterexamples=len(names) if bad else 0,proved=0 if bad else len(names),smt2_sha256=digest(job),answer_sha256=digest(d/'law.log'))
    return dict(scope='One-edge induction and combinational enabled read laws for the actual sealed RAM leaves including flat adapters, all 128 addresses and whole words. Two-state defined data after first write. No reset semantics or claim for unwritten/disabled/X reads, optimized netlists, timing or CPU performance.',stock_seal=ref['stock_board_seal'],candidate_seal=ref['candidate_board_input_seal'],yosys=subprocess.check_output([yosys,'-V'],text=True).strip(),z3=subprocess.check_output([z3,'-version'],text=True).strip(),yosys_sha256=digest(yosys),z3_sha256=digest(z3),flat_writer_to_parent_port=parents,cases=cases)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('stock','lvt','out'):p.add_argument(n,type=Path)
    p.add_argument('--yosys',type=Path,required=True);p.add_argument('--z3',type=Path,required=True);v=p.parse_args();res=solve(*(getattr(v,n).resolve() for n in ('stock','lvt','out','yosys','z3')));(v.out/'result.json').write_bytes((json.dumps(res,indent=2)+'\n').encode());print('REGISTER_FILE_WORD_LAWS_PROVED_AND_CONTROLS_REJECTED_NOT_TIMING')
