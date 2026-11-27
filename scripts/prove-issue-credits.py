#!/usr/bin/env python3
"""Check registered dispatch credits from two real BOOM elaborations, after one edge.
Generated Verilog and solver transcripts stay in the supplied fresh local directory.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

QUEUES = {
    'IssueUnitCollapsing.sv': (32,'f8603d9f22a80a730d4424a16b2bf4e9a95d480a3ea86d7f19f0859fc24ffef6'),
    'IssueUnitCollapsing_1.sv': (24,'79fb7edd37d8dfd782877b7c8980825fab420a2bec0f688523ceafcee8a97917'),
    'IssueUnitCollapsing_2.sv': (40,'af0a6ce24faafd5867336e055cd6511cfb083d1deda7002e17e1ee5da2ec631f'),
}
LEAF = re.compile(r'(?:\()?~_slots_(\d+)_io_will_be_valid(?: \| (?:~_slots_0_io_valid|\(\|[\w]+\))\))? & ~issue_slots_(\d+)_in_uop_valid')


def extract(raw, n, partial):
    text = re.sub(r'//[^\n]*', '', raw.decode())
    leaves = []
    def replace_leaf(m):
        i = len(leaves)
        if int(m[1]) != i or int(m[2]) != i:
            raise ValueError('slot order or signal mismatch')
        leaves.append(m[0]); return 'a[%d]' % i
    (width, total), = re.findall(r'wire\s+\[(\d+):0\]\s+num_available\s*=\s*([^;]+);', text)
    total = LEAF.sub(replace_leaf, total)
    if not re.fullmatch(r"[\d\sah',+{}\[\]]+", re.sub(r'vcuAvailPartials_\d+', 'a', total)):
        raise ValueError('unrecognized total expression')
    key = r'vcuAvailPartials_\d+' if partial else r'io_dis_uops_\d+_ready_REG'
    # Require exactly one uninterrupted set of unconditional nonblocking assignments.
    clock_pattern = r'always @\(posedge clock\) begin\s*((?:(?:'+key+r')\s*<=\s*[^;]+;\s*)+)end\b'
    (clocked,) = re.findall(clock_pattern, text)
    updates = re.findall(r'('+key+r')\s*<=\s*([^;]+);', clocked)
    names = [('vcuAvailPartials_%d'%i if partial else 'io_dis_uops_%d_ready_REG'%i)
             for i in range(n//4 if partial else 4)]
    if [k for k,_ in updates] != names or len(re.findall(r'\b(?:'+key+r')\s*<=',text)) != len(names):
        raise ValueError('register coverage')
    decls=[]; seq=[]
    for i,(name,rhs) in enumerate(updates):
        (shape,) = re.findall(r'\breg\s+(\[\d+:0\]\s+)?'+name+r'\s*;',text)
        if shape.strip() != ('[2:0]' if partial else ''): raise ValueError('register width')
        decls.append('reg '+shape+name+';')
        rhs=LEAF.sub(replace_leaf,rhs)
        if partial and (len(leaves)!=4*i+4 or not re.fullmatch(r"[\d\sah',+{}\[\]]+",rhs)): raise ValueError('partial expression')
        seq.append(name+' <= '+rhs+';')
    if len(leaves)!=n: raise ValueError('availability leaves')
    outputs=re.findall(r'\bassign io_dis_uops_(\d+)_ready\s*=\s*([^;]+);',text)
    if [i for i,_ in outputs]!=['0','1','2','3']: raise ValueError('ready ports')
    for i,expr in enumerate([rhs for _,rhs in (outputs if partial else updates)]):
        if not re.fullmatch(r"(?:num_available|[\d\sh'|>():\[\]])+",expr): raise ValueError('unknown ready logic')
        if not partial and outputs[i][1]!=names[i]: raise ValueError('missing direct ready register')
    body = decls+['wire [%s:0] num_available = %s;'%(width,total),'always @(posedge clock) begin',*seq,'end']
    body+=['assign r[%s] = %s;' % pair for pair in outputs]
    # Remove only the constructs extracted above plus corresponding random-init
    # assignments. Every remaining HDL token (including wiring) must match.
    rest = re.sub(clock_pattern, '', text)
    def remove(pattern):
        nonlocal rest
        rest,count = re.subn(pattern, '', rest)
        if count!=1: raise ValueError('unexpected extra or missing extracted statement')
    remove(r'wire\s+\[\d+:0\]\s+num_available\s*=\s*[^;]+;')
    for i,name in enumerate(names):
        remove(r'\breg\s+(?:\[2:0\]\s+)?'+name+r'\s*;')
        bits='%d:%d'%(3*i+2,3*i) if partial else str(i)
        remove(r"\b"+name+r" = _RANDOM\[/\*Zero width\*/ 1'b0\]\["+bits+r"\];")
    for i,_ in outputs: remove(r'\bassign io_dis_uops_'+i+r'_ready\s*=\s*[^;]+;')
    return leaves,'\n'.join(body),' '.join(rest.split())


def miter(n, old, new, mutate):
    defs=[]
    for name,body in [('reference',old),('candidate',new)]:
        defs.append('module %s(input clock, input [%d:0] a, output [3:0] r);\n%s\nendmodule' % (name,n-1,body))
    # Negative control drops precisely the last availability bit in the candidate only.
    inp="{1'b0,a[%d:0]}"%(n-2) if mutate else 'a'
    return '\n'.join(defs)+'''\nmodule miter(input clock,input [%d:0] a,output ok,output [3:0] orig,changed);
      reference refq(clock,a,orig); candidate newq(clock,%s,changed); assign ok=orig==changed;
    endmodule\n'''%(n-1,inp)


def inventory(stock,variant):
    old, new = 'PerfMegaBoomVCU118Config','PerfPartialMegaBoomVCU118Config'
    def files(directory,config):
        root=directory.parent
        if directory.name!='gen-collateral' or not root.name.endswith('.'+config):raise ValueError('unexpected generator directory')
        paths=[Path(v).resolve(strict=True) for v in (root/(root.name+'.vsrcs.f')).read_text().splitlines() if v.strip()]
        if len(paths)!=548 or len(set(p.name for p in paths))!=len(paths):raise ValueError('unexpected HDL inventory')
        return paths
    paths,others=files(stock,old),files(variant,new); changes=set(); digests=[sha256(),sha256()]
    for a,b in zip(paths,others):
        if a.name.replace(old,new)!=b.name:raise ValueError('changed source order')
        ha,hb=(sha256(v.read_bytes()).hexdigest() for v in (a,b))
        for d,p,h in zip(digests,(a,b),(ha,hb)):d.update((h+'  '+p.name+'\n').encode())
        if ha!=hb:
            if a.parent!=stock.resolve() or b.parent!=variant.resolve():raise ValueError('unexpected changed source location')
            changes.add(a.name)
    if changes!=set(QUEUES):raise ValueError('HDL changed outside the three issue queues')
    return dict(ordered_hdl_inputs=len(paths),byte_identical=len(paths)-len(changes),changed_files=sorted(changes),ordered_hashes_and_basenames_sha256=[d.hexdigest() for d in digests])


def counterexample(log,n):
    def bits(time,name,width):
        (v,)=re.findall(r'^\s*'+str(time)+r'\s+\\'+name+r'\s+[\d-]+\s+[a-fA-F0-9-]+\s+([01]{'+str(width)+r'})\s*$',log,re.M)
        return v
    a=bits(1,'a',n); ref=int(bits(2,'orig',4),2); got=int(bits(2,'changed',4),2)
    mask=lambda pop: (1 << min(4,pop))-1
    if a[0]!='1' or ref==got or (ref,got)!=(mask(a.count('1')),mask(a[1:].count('1'))):raise ValueError('counterexample does not reproduce the dropped slot')
    return dict(input_hex=format(int(a,2),'x'),reference_ready=ref,mutant_ready=got)


def run(stock, variant, out, solver, seconds):
    full=inventory(stock,variant); out.mkdir(); records={}; solver=str(solver)
    version=subprocess.check_output([solver,'-V'],text=True).strip()
    for name,(n,pin) in QUEUES.items():
        raws=[(d/name).read_bytes() for d in (stock,variant)]
        hashes=[sha256(raw).hexdigest() for raw in raws]
        if hashes[0]!=pin: raise ValueError('stock queue identity')
        (la,old,outer),(lb,new,other)=[extract(raw,n,i==1) for i,raw in enumerate(raws)]
        if la!=lb: raise ValueError('changed availability predicates')
        if outer!=other:raise ValueError('queue logic outside measured cone changed')
        witness=None
        for bad in (True,False):
            tag='%d-%s'%(n,'drop' if bad else 'exact'); rtl=out/(tag+'.v'); log=out/(tag+'.txt')
            rtl.write_text(miter(n,old,new,bad)); proof='-falsify' if bad else '-verify'
            command='read_verilog %s; prep -top miter -flatten; sat -seq 2 -prove-skip 1 -set-def-inputs -prove ok 1 %s -timeout %d -show a,orig,changed' % (rtl.name,proof,seconds)
            with log.open('w') as f:
                res=subprocess.run([solver,'-Q','-T','-p',command],cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=seconds+45)
            transcript=log.read_text()
            marker='SAT proof finished - '+('model found: FAIL!' if bad else 'no model found: SUCCESS!')
            if res.returncode or transcript.count(marker)!=1: raise ValueError('inconclusive proof: '+tag)
            if bad: witness=counterexample(transcript,n)
            print(tag,'counterexample confirmed' if bad else 'equivalent',flush=True)
        records[name]=dict(slots=n,registered_4_slot_groups=n//4,reference_sha256=hashes[0],candidate_sha256=hashes[1],identical_availability_predicates=n,unconstrained_vectors=2**n,ready_lanes=4,last_slot_drop_counterexample=witness,all_lanes_equivalent_after_one_edge=True)
    return dict(scope='Two-state one-edge dispatch-ready cones, arbitrary shared availability vector. Uninitialized outputs before first edge, upstream slot logic, whole-core functionality, PPA and board CoreMark are outside the proof.',solver=version,hdl_inventory=full,queues=records)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('stock','candidate','out'):p.add_argument(arg,type=Path)
    p.add_argument('--yosys',default='yosys');p.add_argument('--timeout',default=90,type=int);a=p.parse_args()
    result=run(a.stock,a.candidate,a.out,a.yosys,a.timeout);(a.out/'proof.json').write_text(json.dumps(result,indent=2)+'\n')
