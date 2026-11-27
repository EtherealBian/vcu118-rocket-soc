#!/usr/bin/env python3
"""Build and prove both move-valid cones from the actual, sealed 40-slot queue."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess

D=runpy.run_path(str(Path(__file__).with_name('derive-mega-miss-select.py')))
need,one,UNIT,SLOT,ALT,MOV=[D[n] for n in ('need','one','UNIT','SLOT','ALT','MOV')]
INPUTS={'state':80, 'grant':40, 'ready1':40, 'ready2':40, 'pred':40, 'poison1':40,'poison2':40,'s4':40,'s3':40,'s2':40,'s1':40,'dis':4,'miss':1}
WIDTH=lambda w:f'[{w-1}:0] ' if w>1 else ''

def field(text,rex):
    v=re.findall(rex,text,re.M);need(len(v)==1,'missing or duplicate: '+rex);return v[0]

def extract(src,alt,top):
    u,slot=(alt.split('\nmodule '+ALT+'(',1) if alt else (src[UNIT],src[SLOT]));kind=ALT if alt else SLOT
    # Map each selector *by net name* in the original; this permits all bit patterns,
    # including simultaneous selects, rather than assuming a one-hot priority mux.
    subs={D['DIS3']:'dis[3]', **{'will_be_valid_'+str(40+i):f'dis[{i}]' for i in range(3)}, 'io_ld_miss':'miss'}
    stock_moves=list(MOV.finditer(src[UNIT]));need(len(stock_moves)==40,'expected 40 destinations')
    for i,m in enumerate(stock_moves):
        ex=m[3]; ids=re.findall(r'\b_GEN_\d+(?= \?)',ex);need(len(ids)==3 and not any(x in subs for x in ids),'inconsistent selectors')
        subs.update({g:f'{v}[{i}]' for g,v in zip(ids,('s4','s3','s2'))}); subs[["~_slots_0_io_valid","_next_1_1to0 == 2'h1"][i] if i<2 else f"next_{i} == 4'h1"]=f's1[{i}]'
    # Avoid substring substitution inside e.g. _GEN_219 or a different wire.
    rx=re.compile('(?<![\\w$])(?:'+'|'.join(re.escape(k) for k in sorted(subs,key=len,reverse=True))+')(?![\\w$])')
    norm=lambda expr:rx.sub(lambda m:subs[m[0]],expr)
    body=['module '+top+'('+', '.join(['input '+WIDTH(w)+k for k,w in INPUTS.items()]+['output [39:0] move, keep'])+');']
    for i in range(40):
        inst=field(u,rf'^  {kind} slots_{i} \(([^;]*?)\);'); bind=dict(re.findall(r'\.(\w+)\s*\(\s*(\w+)\s*\)',inst))
        need(bind['io_ldspec_miss']=='io_ld_miss' and bind['io_grant']==f'issue_slots_{i}_grant' and bind['io_will_be_valid']==f'_slots_{i}_io_will_be_valid','different slot wiring')
        f={ 'state':f'state[{2*i+1}:{2*i}]','io_grant':f'grant[{i}]','p1':f'ready1[{i}]','p2':f'ready2[{i}]','ppred':f'pred[{i}]','p1_poisoned':f'poison1[{i}]','p2_poisoned':f'poison2[{i}]','io_ldspec_miss':'miss'}
        for n in ('_may_vacate_T','_may_vacate_T_1'):
            decl=field(slot,r'^  wire +'+n+r' = ([^;]+);'); f[n]='('+decl.replace('state',f['state'])+')'
        def slot_rhs(n):
            expr=field(slot,r'^  assign '+n+r' = ([^;]+);');return re.sub(r'\b[A-Za-z_]\w*',lambda m:f.get(m[0],m[0]),expr)
        for out in (['io_will_be_valid','vcu_base','vcu_poison'] if alt else ['io_will_be_valid']):
            body.append('wire '+bind[out]+' = '+slot_rhs(out)+';')
        body.append(f'assign keep[{i}] = '+bind['io_will_be_valid']+';')
    for i in range(40):
        if alt and i<39:
            for name in ('vcu_moved_base_','vcu_moved_poison_'):
                n=name+str(i); body.append(f'wire {n} = '+norm(field(u,'^  wire '+n+r' = ([^;]+);'))+';')
        body.append(f'assign move[{i}] = '+norm(field(u,r'^  wire +issue_slots_'+str(i)+r'_in_uop_valid = ([^;]+);'))+';')
    return '\n'.join(body+['endmodule',''])

def wrapper():
    decl=', '.join('input '+WIDTH(w)+n for n,w in INPUTS.items());s=[f'module miss_boundary(input clock, {decl}, output [39:0] move, keep);']
    for n,w in INPUTS.items(): s+=['(* DONT_TOUCH="yes" *) reg '+WIDTH(w)+'q_'+n+';',f'always @(posedge clock) q_{n} <= {n};']
    s+=['wire [39:0] m, k; (* DONT_TOUCH="yes" *) reg [39:0] qm, qk;', 'always @(posedge clock) begin qm<=m; qk<=k; end', 'assign move=qm; assign keep=qk;', 'cone dut('+','.join(f'.{n}(q_{n})' for n in INPUTS)+',.move(m),.keep(k));','endmodule',''];return '\n'.join(s)

def run(kit,fresh,yosys):
    orig=D['sealed'](kit);alt=D['derive'](orig); fresh.mkdir(); proofs={};digest=lambda b:sha256(b).hexdigest()
    clean=extract(orig,None,'cone'); (fresh/'stock.v').write_bytes(clean.encode());(fresh/'boundary.v').write_bytes(wrapper().encode());(fresh/'clock.xdc').write_bytes(b'create_clock -name cpu -period 5.714 [get_ports clock]\n');(fresh/(UNIT+'.sv')).write_bytes(alt.encode())
    for label,var in [('candidate',alt),('omit_p2_poison',one(alt,'assign vcu_poison = (|state) & (p1_poisoned | p2_poisoned);','assign vcu_poison = (|state) & p1_poisoned;')),('cross_slot9',one(alt,"next_8 == 4'h1 & vcu_poison_9;", "next_8 == 4'h1 & vcu_poison_10;"))]:
        case=extract(orig,var,'cone'); (fresh/(label+'.v')).write_bytes(case.encode()); (fresh/(label+'.ys')).write_text(f'read_verilog -noautowire stock.v; rename cone gold; read_verilog -noautowire {label}.v; rename cone gate\nmiter -equiv -flatten gold gate compare; hierarchy -check -top compare; proc; opt; check -assert; sat -prove trigger 0 compare\n')
        proc=subprocess.run([str(yosys),'-Q','-T','-s',label+'.ys'],cwd=fresh,capture_output=True,text=True,timeout=180); (fresh/(label+'.log')).write_text(proc.stdout+proc.stderr);a='SAT proof finished - no model found: SUCCESS!';b='SAT proof finished - model found: FAIL!';need(proc.returncode==0 and proc.stdout.count(a)==int(label=='candidate') and proc.stdout.count(b)==int(label!='candidate'),label+' did not give the expected decision');proofs[label]='equivalent' if label=='candidate' else 'counterexample'
    result=dict(scope='Two-state combinational equivalence of actual resident source and move-valid cones; abstract slot inputs, independent priority controls and dispatch eligibilities. No full-chip timing or board score.',board_kit_sha256=D['KIT'],stock_sha256=D['HASH'],candidate_unit_sha256=digest(alt.encode()),solver_sha256=digest(yosys.read_bytes()),cone_sha256={k:digest((fresh/k).read_bytes()) for k in ['stock.v','candidate.v','boundary.v','clock.xdc']},sat=proofs,input_bits=sum(INPUTS.values()),resident_valid_outputs=40,move_valid_outputs=40,changed_destinations=39)
    (fresh/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('INT_MISS_MOVE_40_CONE_PROOF_AND_NEGATIVES_COMPLETE')

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('kit',type=Path);ap.add_argument('fresh',type=Path);ap.add_argument('--yosys',type=Path,required=True);a=ap.parse_args();run(a.kit.resolve(),a.fresh.resolve(),a.yosys.resolve())
