#!/usr/bin/env python3
"""Derive and prove a data-mux-only variant of the sealed four-wide INT issue unit.

All grant, wakeup and readiness logic is unchanged. No generated upstream HDL
is checked in. A physical experiment is separate and needs its own clean build.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

KIT = 'b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'
UNIT = 'af0a6ce24faafd5867336e055cd6511cfb083d1deda7002e17e1ee5da2ec631f'
NAME = 'IssueUnitCollapsing_2.sv'
G = r'_GEN_\d+'
FIELD = re.compile(r'^(  assign io_iss_uops_([0-3])_(\w+) = )([^;]+)(;[^\n]*)$', re.M)
digest = lambda b: sha256(b).hexdigest()


def grants(src):
    ports = []
    for p in range(4):
        line, = re.findall(r'^  assign io_iss_valids_'+str(p)+r' = ([^;]+);', src, re.M)
        names = line.split(' | ')[::-1]
        if len(names)!=40 or not all(re.fullmatch(G,n) for n in names):
            raise ValueError('expected 40 grant wires per port')
        ports.append(names)
    if len(set(sum(ports, [])))!=160:
        raise ValueError('duplicate grant in ports')
    # Match each independent slot grant to the same four port decisions. This
    # also binds the descending order in the output-valid equations to slot IDs.
    for i in range(40):
        rhs, = re.findall(r'^  assign issue_slots_'+str(i)+r'_grant = ([^;]+);',src,re.M)
        if rhs.split(' | ') != [ports[p][i] for p in reversed(range(4))]:
            raise ValueError('grant/slot identity mismatch')
    return ports


def balanced(terms):
    if not terms:raise ValueError('empty reduction')
    while len(terms)>1:
        terms=['('+terms[i]+' | '+terms[i+1]+')' if i+1<len(terms) else terms[i] for i in range(0,len(terms),2)]
    return terms[0]


def mask_mux(gs, data, width, default, valid):
    if not gs or len(gs)!=len(data) or width<1 or width>64 or not 0<=default<(1<<width):
        raise ValueError('incomplete payload or unrepresentable idle value')
    terms=['({'+str(width)+'{'+g+'}} & '+v+')' for g,v in zip(gs,data)]
    if default:
        terms.append("({"+str(width)+'{~'+valid+"}} & "+str(width)+"'h"+format(default,'x')+')')
    return balanced(terms)


def parse_field(expr, gs, field):
    terms=expr.split(' : ');last=terms.pop()
    c=re.fullmatch(r"(\d+)'h([0-9a-f]+)", last)
    if c:width,default=int(c[1]),int(c[2],16)
    else:
        if last!=gs[0]+' & _slots_0_io_uop_'+field:raise ValueError('unknown single-bit fallback')
        terms.append(gs[0]+' ? _slots_0_io_uop_'+field);width,default=1,0
    data=['_slots_'+str(i)+'_io_uop_'+field for i in range(40)]
    if not 0<width<=64 or not 0<=default<2**width or terms!=[g+' ? '+v for g,v in reversed(list(zip(gs,data)))]:
        raise ValueError('wrong order, data, grant or fallback')
    return data,width,default


def derive(src):
    gs=grants(src); fields={}; counts=Counter()
    def change(m):
        port,name=int(m[2]),m[3]; data,width,default=parse_field(m[4],gs[port],name)
        key=port,name
        if key in fields:raise ValueError('duplicate output field')
        fields[key]=width,default;counts[port]+=1
        return m[1]+mask_mux(gs[port],data,width,default,'io_iss_valids_'+str(port))+m[5]
    out=FIELD.sub(change,src)
    widths={name:int(msb)+1 if msb else 1 for msb,name in re.findall(
        r'^  (?:wire|output)\s+(?:\[(\d+):0\]\s+)?((?:_slots_\d+_io_uop_|io_iss_uops_\d_)[a-zA-Z0-9_]+)[,; ]',src,re.M)}
    for (p,n),(width,_) in fields.items():
        names=[f'io_iss_uops_{p}_{n}']+[f'_slots_{i}_io_uop_{n}' for i in range(40)]
        if any(widths.get(k)!=width for k in names):raise ValueError('payload output/slot width mismatch')
    if counts!={0:69,1:30,2:30,3:30}:raise ValueError('incomplete integer output payload')
    return out,gs,fields


def cone(src, gs):
    lines=[s.split('//')[0].strip() for s in src.splitlines()]
    a,=[i for i,s in enumerate(lines) if re.fullmatch(r'wire\s+_GEN_141 = .+;',s)]
    b,=[i for i,s in enumerate(lines) if s.startswith('assign issue_slots_39_grant = ')]
    body=lines[a:b+1]
    if len(body)!=622 or any(not re.fullmatch(r'(?:wire\s+|assign ).+;',s) for s in body):raise ValueError('unexpected grant cone')
    ins=['input [9:0] io_fu_types_'+str(p) for p in (0,2,3)]
    for i in range(40): ins+=['input _slots_%d_io_request'%i,'input [9:0] _slots_%d_io_uop_fu_code'%i]
    outs=['output [39:0] gr%d'%p for p in range(4)]
    decl=['wire issue_slots_%d_grant;'%i for i in range(40)]
    return 'module arb('+', '.join(ins+outs)+');\n'+'\n'.join(decl+body+['assign gr%d = {'%p+','.join(gs[p][::-1])+'};' for p in range(4)])+'\nendmodule\n',ins


def miter_port(arb,ins,port,mutate):
    signals=['gr%d'%p for p in range(4)];g=signals[port]
    wire='wire [39:0] '+', '.join(signals)+';'
    inst='arb a('+', '.join([s.split()[-1] for s in ins]+signals)+');'
    if mutate:
        # Artificially assert slot 0 alongside any selected nonzero slot.
        wire+=' wire [39:0] bad = '+g+" | {39'd0,(|"+g+'[39:1])};'
        prop="!(|(bad & (bad-40'd1)))"
    else:prop='!(|('+g+' & ('+g+"-40'd1)))"
    return arb+'module top('+', '.join(ins+['output ok'])+');\n'+wire+'\n'+inst+'\nassign ok = '+prop+';\nendmodule\n'


def payload_exprs(n,default):
    gs=['g[%d]'%i for i in range(n)]; ds=['d[%d]'%i for i in range(n)]
    # All vectors in the sealed selector are bitwise; projecting an output bit
    # gives exactly this chain and masked reduction. Both idle-bit values exist.
    ref=''.join(g+' ? '+v+' : ' for g,v in reversed(list(zip(gs,ds))))+"1'b"+str(default)
    return ref,mask_mux(gs,ds,1,default,'valid')


def miter_payload(default,mutate):
    ref,alt=payload_exprs(40,default)
    if mutate:alt=alt.replace(' & d[39])',' & d[38])')
    return "module top(input [39:0] g,d,output ok);wire valid=|g;wire one=!(|(g & (g-40'd1)));\nwire orig="+ref+';\nwire alt='+alt+';\nassign ok=!one || (orig==alt); endmodule\n'


def proof(out,name,text,solver,mutant=False):
    f=out/(name+'.v');f.write_bytes(text.encode())
    cmd='read_verilog -noautowire '+f.name+'; prep -top top -flatten; sat -timeout 90 -prove ok 1 -show-inputs -show-outputs'
    r=subprocess.run([solver,'-Q','-T','-p',cmd],cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=130)
    (out/(name+'.log')).write_bytes(r.stdout);log=r.stdout.decode();r.check_returncode();expect='SAT proof finished - '+('model found: FAIL!' if mutant else 'no model found: SUCCESS!')
    if log.splitlines().count(expect)!=1:raise ValueError('inconclusive or incorrect solver outcome: '+name)
    if mutant and not re.search(r'^\s*\\ok\s+0\s+0\s+0\s*$',log,re.M):raise ValueError('missing negative witness')
    return {'cone_sha256':digest(f.read_bytes()),'result':'counterexample' if mutant else 'proved'}


def run(kit,out,solver):
    unit=kit/'rtl'/NAME;raw=unit.read_bytes();lock=(kit/'CANDIDATE.sha256').read_bytes()
    if digest(lock)!=KIT or digest(raw)!=UNIT or (UNIT+'  rtl/'+NAME) not in lock.decode().splitlines():raise ValueError('wrong sealed physical input')
    out.mkdir();src=raw.decode();changed,gs,fields=derive(src);(out/NAME).write_bytes(changed.encode());arb,ins=cone(src,gs)
    version=subprocess.check_output([solver,'-V'],text=True).strip();results={}
    for p in range(4):
        name='onehot-port-'+str(p);results[name]=proof(out,name,miter_port(arb,ins,p,False),solver)
    for b in (0,1):
        name='payload-idle-'+str(b);results[name]=proof(out,name,miter_payload(b,False),solver)
    results['grant-negative']=proof(out,'grant-negative',miter_port(arb,ins,3,True),solver,True)
    results['payload-negative']=proof(out,'payload-negative',miter_payload(1,True),solver,True)
    return dict(scope='Exact stock two-state combinational port grants and issue payload muxes only. No issue policy, queue depth, or pipeline register changed. Not 4-state equivalence, physical QoR, Linux or a board result.',board_input_seal=KIT,stock_sv_sha256=UNIT,variant_sv_sha256=digest(changed.encode()),solver=version,
                fields_per_port=[sum(p==i for p,_ in fields) for i in range(4)],bits_per_port=[sum(w for (p,n),(w,d) in fields.items() if p==i) for i in range(4)],nonzero_idle_fields=sum(bool(d) for w,d in fields.values()),proofs=results)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--yosys',default='yosys');args=p.parse_args()
    result=run(args.kit,args.out,args.yosys);(args.out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('INT_ISSUE_MUX_PROOFS_ONLY')
