#!/usr/bin/env python3
"""Prove and map a shorter copy/load guard on the actual four BOOM decoders (offline)."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import signal
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
R = runpy.run_path(str(HERE/'test-copy-load-rename.py'))
MAP = runpy.run_path(str(HERE/'map-mega-issue-cut.py'))
FIELDS = ('inst','exception','is_sfb','fp_val','ldst_val','dst_rtype','lrs1_rtype','lrs2_rtype',
          'ldst','lrs1','lrs2','uses_ldq','uses_stq','is_amo','mem_cmd')
W = {f:(32 if f=='inst' else 6 if f in ('ldst','lrs1','lrs2') else 2 if f.endswith('_rtype') else 5 if f=='mem_cmd' else 1) for f in FIELDS}


def digest(b): return sha256(b).hexdigest()
def doc(name): return json.loads((ROOT/'docs'/name).read_bytes())


def equation(src,i):
    pat = rf'(  wire copyload_hit_{i} = )([^;]+);'
    hits = re.findall(pat,src)
    if len(hits)!=1: raise ValueError('expected exactly one candidate guard per lane')
    return hits[0][1]


def reduced(i):
    # Only these three full equations change. The effective-source mux, RAT read,
    # same-packet bypass, held source and recovery machinery remain identical.
    m,l=(f'io_dec_uops_{j}_' for j in (i-1,i))
    return f'''io_dec_fire_{i-1} && io_dec_fire_{i} &&
    !{m}exception && !{l}exception && !{m}is_sfb && !{l}is_sfb &&
    ({m}inst & 32'hfe0ff07f) == 32'h33 && {m}ldst != 0 && {m}lrs2 != 0 && {m}ldst != {m}lrs2 &&
    {l}inst[6:0] == 7'h03 && {l}inst[14:12] != 7 && {l}lrs1 == {m}ldst'''


def variant(full):
    result=full
    for i in (1,2,3): result=R['once'](result,equation(full,i),reduced(i))
    return result


def mux(src,i):
    m=re.findall(rf'  wire \[5:0\] copyload_eff_{i} = ([^;]+);',src)
    if len(m)!=1: raise ValueError('missing effective-source expression')
    return m[0]


def instance(core, signature):
    if core.count(signature)!=1: raise ValueError('unrecognized instance: '+signature)
    return core.split(signature,1)[1].split(');',1)[0]


def connection(body,port,net):
    conns=re.findall(r'\.'+re.escape(port)+r'\s*\(\s*([^()]+?)\s*\)',body)
    if conns!=[net]: raise ValueError('unexpected wiring: '+port)


def fixture(dec,core,leaves,expose=False):
    # All decoder inputs are separate unconstrained top inputs, even CSR/IRQ
    # inputs shared in the SoC. This is a superset, not a trace restriction.
    ports=R['ports'](dec); wires=[]; inputs=[]
    rename=instance(core,'RenameStage rename_stage (')
    for i in range(4):
        decoder=instance(core,f'DecodeUnit decode_units_{i} (')
        connection(rename,f'io_dec_fire_{i}',f'dec_fire_{i}' if i<3 else 'dec_ready')
        args=[]; inputs.append(f'input io_dec_fire_{i}')
        for k,(direction,width) in ports.items():
            if direction=='input':
                n=f'in_{i}_{k}'; inputs.append(f'input {width} {n}')
            elif k.startswith('io_deq_uop_') and k[11:] in FIELDS:
                f=k[11:]; n=f'io_dec_uops_{i}_{f}'
                net=f'_decode_units_{i}_{k}'; connection(decoder,k,net); connection(rename,n,net)
                if width!=('' if W[f]==1 else f'[{W[f]-1}:0]'):
                    raise ValueError('width or decoder-to-rename source differs: '+n)
                wires.append(f'wire {width} {n};')
            else: continue
            args.append(f'.{k}({n})')
        if sum(k.startswith('io_deq_uop_') and k[11:] in FIELDS for k in ports)!=len(FIELDS): raise ValueError('incomplete guard fields')
        wires.append(f'DecodeUnit u{i}('+','.join(args)+');')
    outputs=[]
    if expose:
        # Keep every decode-to-rename field used by the full predicate visible
        # for independent consumers; do not charge the short cut for deleting
        # shared decode logic that still has other users in the full core.
        for i in range(4):
            for f,w in W.items():
                n=f'tap_{i}_{f}'; width='' if w==1 else f'[{w-1}:0] '
                outputs.append(f'output {width}{n}'); wires.append(f'assign {n} = io_dec_uops_{i}_{f};')
    for label,leaf in leaves.items():
        for i in (1,2,3):
            outputs.extend((f'output {label}_hit_{i}',f'output [5:0] {label}_eff_{i}'))
            wires.extend((f'assign {label}_hit_{i} = '+equation(leaf,i)+';',
                          f'assign {label}_eff_{i} = '+mux(leaf,i).replace(f'copyload_hit_{i}',f'{label}_hit_{i}')+';'))
    if len(leaves)==2:
        a,b=leaves
        def packed(x): return '{'+','.join(f'{x}_{sig}_{i}' for i in (1,2,3) for sig in ('hit','eff'))+'}'
        outputs.append('output equal'); wires.append(f'assign equal = {packed(a)} == {packed(b)};')
    return 'module top('+',\n'.join(inputs+outputs)+');\n'+'\n'.join(wires)+'\nendmodule\n'


def execute(yosys,d,commands,name):
    log=d/(name+'.log')
    with log.open('xb') as f:
        cmd=[yosys,'-Q','-T','-p',commands]
        with subprocess.Popen(cmd,cwd=d,stdout=f,stderr=subprocess.STDOUT,start_new_session=True) as child:
            try: rc=child.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL); child.wait(); raise
            if rc: raise subprocess.CalledProcessError(rc,cmd)
    return log.read_text()


PASS='SAT proof finished - no model found: SUCCESS!'
FOUND='SAT solving finished - model found:'


def proof_sections(log):
    return re.split(r'^\d+\. Executing SAT pass .*?\n',log,flags=re.M)[1:]


def check_proof(block,signal,value):
    if (block.splitlines().count(PASS)!=1 or 'Final constraint equation: { } = { }' not in block.splitlines()
            or f"Final proof equation: \\{signal} = 1'{value}" not in block.splitlines()):
        raise ValueError('not an unconstrained equivalence proof')


def witness(block, constrained, value, fields):
    lines=block.splitlines()
    if lines.count(FOUND)!=1 or f"Final constraint equation: \\{constrained} = 1'{value}" not in lines:
        raise ValueError('missing exact witness')
    for name,bit in fields.items():
        if re.findall(r'^  \\'+name+r'[ \t]+(\d+)[ \t]+(\S+)[ \t]+(\S+)[ \t]*$',block,re.M)!=[(str(bit),)*3]:
            raise ValueError('missing or wrong witness bit: '+name)


def check_pair(log):
    blocks=proof_sections(log)
    if len(blocks)!=7: raise ValueError('missing proof or reachability run')
    check_proof(blocks[0],'equal',1)
    for block,(i,v) in zip(blocks[1:],((i,v) for i in (1,2,3) for v in (0,1))):
        n=f'full_hit_{i}'; witness(block,n,v,{n:v})


def sequential(rtl,simple,out,cc,vvp,ivl):
    ref=doc('perf-copy-load-rename.json'); src={k:(rtl/(k+'.sv')).read_bytes() for k in R['LOCK']}
    if {k:digest(v) for k,v in src.items()}!=R['LOCK']: raise ValueError('wrong sequential test inputs')
    d=out/'paired'; d.mkdir(); bench=ROOT/'tests/copy_load_rename_tb.v'
    wrapper=R['fixture']({k:v.decode() for k,v in src.items()}).encode()
    if digest(wrapper)!=ref['wiring_sha256'] or digest(bench.read_bytes())!=ref['bench_sha256']: raise ValueError('changed directed bench')
    (d/'wiring.svh').write_bytes(wrapper); (d/'short.sv').write_bytes(R['once'](simple,'module RenameStage(','module RenameStageCopyLoad(').encode())
    cmd=[cc]+(['-B',str(ivl)] if ivl else [])+['-g2012','-DSYNTHESIS','-s','tb','-I','.','-o','test.vvp',str(bench),'short.sv']+[str(rtl/(k+'.sv')) for k in src]
    subprocess.run(cmd,cwd=d,check=True,timeout=90)
    vp=subprocess.run([vvp,'-N']+(['-M',str(ivl)] if ivl else [])+['test.vvp'],cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True,timeout=90)
    (d/'run.txt').write_text(vp.stdout)
    if vp.stdout.strip()!='COPYLOAD_RENAME_PASS cases=22': raise ValueError('directed test did not complete')
    ver=subprocess.check_output([cc]+(['-B',str(ivl)] if ivl else [])+['-V'],stderr=subprocess.DEVNULL,text=True).splitlines()[0]
    return dict(cases=22,simulator=ver,bench_sha256=ref['bench_sha256'],wiring_sha256=ref['wiring_sha256'])


def map_cut(d,Y,read,dec,expose):
    # Write only the flattened cone, ending immediately before ABC. Free the
    # elaborator before running ABC, without cutting or tying off any signal.
    execute(Y,d,read+'synth_xilinx -top top -family xcup -flatten -run begin:map_luts; select top; write_ilang -selected split.il','lower')
    y=execute(Y,d,'read_verilog -lib +/xilinx/cells_sim.v; read_ilang split.il; synth_xilinx -top top -family xcup -run map_luts:; check -assert; write_json mapped.json; select top; write_ilang -selected mapped.il','map')
    if [s for s in y.splitlines() if s.startswith('Running ABC command:')]!=['Running ABC command: berkeley-abc -s -f <abc-temp-dir>/abc.script 2>&1']: raise ValueError('unidentified mapper')
    net=json.loads((d/'mapped.json').read_bytes())['modules']['top']; spec={f'cut_{sig}_{i}':w for i in (1,2,3) for sig,w in [('hit',1),('eff',6)]}
    if expose: spec.update({f'tap_{i}_{f}':w for i in range(4) for f,w in W.items()})
    widths={f'in_{i}_{k}':1+int(w[1:].split(':')[0]) if w else 1 for i in range(4) for k,(direction,w) in R['ports'](dec).items() if direction=='input'}
    widths.update({f'io_dec_fire_{i}':1 for i in range(4)})
    pins={k:p['bits'] for k,p in net['ports'].items() if p['direction']=='input'}; bits=[b for bs in pins.values() for b in bs]
    if {k:len(bs) for k,bs in pins.items()}!=widths or len(set(bits))!=len(bits) or any(type(b)!=int for b in bits): raise ValueError('cut inputs aliased or constrained')
    result=MAP['topology'](net,spec)
    # Check the mapped netlist including primitive truth tables against the RTL
    # (not just the number of ports on a successfully mapped graph).
    y=execute(Y,d,'read_ilang mapped.il; rename top mapped; read_verilog +/xilinx/cells_sim.v; '+read+'proc; miter -equiv -flatten top mapped cmp; hierarchy -check -top cmp; flatten; opt; check -assert; sat -verify -prove trigger 0','netproof')
    blocks=proof_sections(y)
    if len(blocks)!=1: raise ValueError('missing mapped proof')
    check_proof(blocks[0],'trigger',0)
    if expose:
        levels=result['max_primitive_levels']
        result['tap_levels_max_across_lanes']={f:max(levels.pop(f'tap_{i}_{f}') for i in range(4)) for f in W}
    return dict(fixture_sha256=digest((d/'top.v').read_bytes()),mapped_vs_rtl='proved',**result)


def run(kit,cand,out,yosys,cc,vvp,ivl):
    ref=doc('perf-copy-load-model.json'); sources={k:(kit/'rtl'/(k+'.sv')).read_bytes() for k in ('DecodeUnit','BoomCore','RenameStage')}
    manifest=(kit/'CANDIDATE.sha256').read_bytes(); modified=(cand/'rtl/RenameStage.sv').read_bytes()
    if (digest(manifest)!=ref['original_seal'] or digest((cand/'CANDIDATE.sha256').read_bytes())!=ref['candidate_seal'] or
        any(f'{digest(v)}  rtl/{k}.sv' not in manifest.decode().splitlines() for k,v in sources.items()) or
        digest(sources['DecodeUnit'])!=R['LOCK']['DecodeUnit'] or digest(modified)!=ref['changed']['rtl/RenameStage.sv']):
        raise ValueError('wrong source pair')
    full=modified.decode(); simple=variant(full)
    if full!=R['candidate'](sources['RenameStage'].decode()):raise ValueError('full reference differs from sealed candidate')
    dec,core=[sources[k].decode() for k in ('DecodeUnit','BoomCore')]
    tool=doc('perf-mega175-issue-map-36.json'); abc=shutil.which('berkeley-abc'); Y=Path(yosys)
    if (not abc or digest(Path(abc).read_bytes())!=tool['abc_sha256'] or digest(Y.read_bytes())!=tool['yosys_sha256'] or
            subprocess.check_output([Y,'-V'],text=True).strip()!=tool['solver']):raise ValueError('wrong solver or mapper')
    if out.exists() or any(out in p.parents or p in out.parents or p==out for p in (kit,cand)): raise ValueError('use a fresh directory outside both sealed kits')
    out.mkdir(); (out/'RenameStage-short.sv').write_bytes(simple.encode())
    paired=sequential(kit/'rtl',simple,out,cc,vvp,ivl)
    def make(name,leaves,expose=False):
        d=out/name;d.mkdir(); (d/'DecodeUnit.sv').write_bytes(sources['DecodeUnit'])
        (d/'top.v').write_bytes(fixture(dec,core,leaves,expose).encode());return d
    proof=make('proof',{'full':full,'short':simple})
    read='read_verilog -sv -noautowire DecodeUnit.sv top.v; '
    prep=read+'prep -top top -flatten; check -assert; '
    # Unconstrained equality for all hit bits and source values. Separately
    # exclude a vacuous pass for each lane with reachable match and nonmatch.
    y=execute(Y,proof,prep+'sat -verify -prove equal 1; '+'; '.join(f'sat -set full_hit_{i} {v}' for i in (1,2,3) for v in (0,1)), 'proof')
    check_pair(y)
    control={}
    for name,i,old,new in [('allow_copy_sfb',1,'!io_dec_uops_0_is_sfb',"1'b1"),
                           ('ignore_load_exception',2,'!io_dec_uops_2_exception',"1'b1"),
                           ('disable_lane_3',3,'io_dec_fire_3',"1'b0")]:
        eq=equation(simple,i); broken=R['once'](simple,eq,R['once'](eq,old,new)); d=make(name,{'full':full,'bad':broken})
        y=execute(Y,d,prep+'sat -set equal 0 -show equal -show full_hit_'+str(i)+' -show bad_hit_'+str(i),'control')
        blocks=proof_sections(y); fullbit=int(name=='disable_lane_3')
        if len(blocks)!=1: raise ValueError('missing negative control')
        witness(blocks[0],'equal',0,{'equal':0,f'full_hit_{i}':fullbit,f'bad_hit_{i}':1-fullbit})
        control[name]=dict(lane=i,full_hit=fullbit,broken_hit=1-fullbit)
    def maps(expose):
        return {name:map_cut(make(('shared-' if expose else '')+name,{'cut':leaf},expose),Y,read,dec,expose)
                for name,leaf in [('full',full),('short',simple)]}
    return dict(scope='Two-state combinational decoder-to-rename equivalence; unplaced xcup mapping of match bits and effective indices, with and without 15 visible decoded fields per lane. Not full rename timing, Fmax, speedup or a board result.',
                full_leaf_sha256=digest(modified),short_leaf_sha256=digest(simple.encode()),decode_unit_sha256=digest(sources['DecodeUnit']),boom_core_sha256=digest(sources['BoomCore']),
                solver=tool['solver'],yosys_sha256=tool['yosys_sha256'],abc_sha256=tool['abc_sha256'],equivalent_bits=21,nonvacuity_witnesses=6,negative_controls=control,paired_rename=paired,mapped=maps(False),mapped_with_shared_fields=maps(True),shared_field_bits=4*sum(W.values()))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('stock_kit','candidate_kit','out','yosys'): p.add_argument(k,type=Path)
    p.add_argument('--iverilog',default='iverilog'); p.add_argument('--vvp',default='vvp'); p.add_argument('--ivl',type=Path)
    a=p.parse_args();r=run(*(getattr(a,k).resolve() for k in ('stock_kit','candidate_kit','out','yosys')),a.iverilog,a.vvp,a.ivl)
    (a.out/'result.json').write_bytes((json.dumps(r,indent=2)+'\n').encode());print('GUARDS_PROVED_AND_MAPPED_NOT_TIMING')
