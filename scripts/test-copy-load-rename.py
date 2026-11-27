#!/usr/bin/env python3
"""Standalone A/B experiment: real expanders, decoders and both four-lane rename pipelines."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
LOCK = dict(RenameStage='c7b12c6a22633b8860309dde54f5b0b5efb937228dfdc15471890a667961349a',
            RenameMapTable='94d7412c2e2256ede6f57fabf4af4cdf75d2e750315a52a4a53764f344d1f17a',
            RenameFreeList='563bb504d96d3ba132443292a8baa1914ef67ece56a610a892f40b2e241320e4',
            RenameBusyTable='80b77e6e5ee1167580bcfc9d97ad3c862e8a4bba9cd807f81cfab478eeb70ba6',
            DecodeUnit='9e9f4b840c3df86376389f9f214a47a87d309fc1273f0e20d339712d2b3b76f4',
            RVCExpander='243e0260b839c395c2f718d6da3226355b4e66634fc9e48e6f02e7a65af0cb4b')


def once(text, a, b):
    if text.count(a) != 1: raise ValueError('unrecognized RTL context: '+a)
    return text.replace(a,b)


def candidate(src):
    # Both instructions still allocate and retire. Change the integer source lookup and
    # its bypass comparisons, not architectural debug metadata or the destination RAT.
    if sha256(src.encode()).hexdigest()!=LOCK['RenameStage']: raise ValueError('wrong RenameStage')
    for i in (1,2,3):
        m,l = (f'io_dec_uops_{j}_' for j in (i-1,i)); raw=l+'lrs1'; eff=f'copyload_eff_{i}'; arch=f'copyload_arch_{i}'
        guard=f'''  reg [5:0] {arch};
  wire copyload_hit_{i} = io_dec_fire_{i-1} && io_dec_fire_{i} &&
    !{m}exception && !{l}exception && !{m}is_sfb && !{l}is_sfb &&
    !{m}fp_val && !{l}fp_val && {m}ldst_val && {m}dst_rtype == 0 &&
    {m}lrs1_rtype == 0 && {m}lrs2_rtype == 0 &&
    ({m}inst & 32'hfe0ff07f) == 32'h33 && {m}lrs1 == 0 &&
    {m}ldst == {{1'b0,{m}inst[11:7]}} && {m}lrs2 == {{1'b0,{m}inst[24:20]}} &&
    {m}ldst != 0 && {m}lrs2 != 0 && {m}ldst != {m}lrs2 &&
    {l}inst[6:0] == 7'h03 && {l}inst[14:12] != 7 && {l}uses_ldq && !{l}uses_stq &&
    !{l}is_amo && {l}mem_cmd == 0 && {l}lrs1_rtype == 0 && {l}dst_rtype == 0 &&
    {raw} == {{1'b0,{l}inst[19:15]}} && {raw} == {m}ldst;
  wire [5:0] {eff} = copyload_hit_{i} ? {m}lrs2 : {raw};
'''
        q=f'  wire [5:0]  next_uop_{i}_lrs1 = _GEN ? r_uop_{i}_lrs1 : {raw};'
        src=once(src,q,guard+q.replace(': '+raw+ ';',': '+eff+';'))
        src=once(src,f'r_uop_{i}_lrs1 <= {raw};', f'{arch} <= {raw};\n      r_uop_{i}_lrs1 <= {eff};')
        q=f'.io_map_reqs_{i}_lrs1        ({raw})'; src=once(src,q,q.replace('('+raw+')','('+eff+')'))
        src=once(src,f'assign io_ren2_uops_{i}_lrs1 = r_uop_{i}_lrs1;',f'assign io_ren2_uops_{i}_lrs1 = {arch};')
    return src


def ports(src):
    header=src.split('module ',1)[1].split(');',1)[0]; result={}
    for line in header.splitlines()[1:]:
        line=line.partition('//')[0].strip().rstrip(',')
        if not line: continue
        m=re.fullmatch(r'(input|output)\s+(?:(\[\d+:0\])\s+)?(\w+)',line)
        if not m: raise ValueError('unknown port: '+line)
        typ,width,name=m.groups(); result[name]=(typ,width or '')
    return result


def zero(width):
    bits=1+int(width[1:].split(':')[0]) if width else 1
    return str(bits)+"'d0"


def fixture(modules):
    dec=ports(modules['DecodeUnit']); ren=ports(modules['RenameStage']); lines=[]
    def inst(module,name,conns): return f'{module} {name}(\n'+',\n'.join(f'  .{k}({v})' for k,v in conns.items())+'\n);'
    renconn={k:k for k,(d,_) in ren.items() if d=='input'}
    for i in range(4):
        lines += [f'wire [31:0] expanded_{i}; wire rvc_{i};',f'RVCExpander ex{i}(.io_in(ins[{i}]),.io_out_bits(expanded_{i}),.io_rvc(rvc_{i}));']
        c={}; spec=dict(io_enq_uop_inst=f'expanded_{i}',io_enq_uop_debug_inst=f'ins[{i}]',io_enq_uop_is_rvc=f'rvc_{i}',io_enq_uop_is_sfb=f'sfb[{i}]',io_enq_uop_xcpt_pf_if=f'fault[{i}]')
        for k,(d,w) in dec.items():
            r=k.replace('io_deq_uop_',f'io_dec_uops_{i}_')
            if d=='output' and r in renconn:
                if ren[r]!=('input',w): raise ValueError('decode/rename port mismatch')
                lines.append(f'wire {w} {r};'); c[k]=r
            elif d=='input': c[k]=spec.get(k,zero(w))
        lines.append(inst('DecodeUnit','dec'+str(i),c))
    spec=dict(clock='clk',reset='rst',io_dis_ready='ready',io_kill='kill',io_wakeups_0_valid='wake',io_wakeups_0_bits_uop_pdst='wp')
    for i in range(4): spec.update({f'io_dec_fire_{i}':f'decfire[{i}]', f'io_dis_fire_{i}':f'disfire[{i}]'})
    for k in renconn:
        if not k.startswith('io_dec_uops_') or k.endswith(('_br_tag','_br_mask')): renconn[k]=spec.get(k,zero(ren[k][1]))
        elif not any(x.endswith(' '+k+';') for x in lines): raise ValueError('unwired decode output: '+k)
    lines.extend([inst('RenameStage','a',renconn),inst('RenameStageCopyLoad','b',renconn)])
    for i in range(4):
        stem=f'io_ren2_uops_{i}_'; names=[k for k,(d,w) in ren.items() if d=='output' and k.startswith(stem) and k not in (stem+'prs1',stem+'prs1_busy')]
        for k in ('prs1','prs2','pdst','stale_pdst','prs1_busy','prs2_busy','lrs1'):
            for u in 'ab': lines.append(f'assign {u}_{k}[{i}]={u}.{stem}{k};')
        lines+= [f'assign am[{i}]=a.io_ren2_mask_{i}; assign bm[{i}]=b.io_ren2_mask_{i};',f'assign astall[{i}]=a.io_ren_stalls_{i}; assign bstall[{i}]=b.io_ren_stalls_{i};']
        # Compare every common architecturally active lane output; unknown padding is not a source oracle.
        vals=lambda u:'{'+','.join(u+'.'+k for k in names)+'}'
        lines.append(f'assign eq[{i}]=({vals("a")} === {vals("b")});')
    return '\n'.join(lines)+'\n'


def run(rtl,out,cc,vvp,ivl):
    rtl=rtl.resolve(strict=True);out=out.resolve()
    if out.exists() or rtl in out.parents or out in rtl.parents: raise ValueError('use a new directory outside RTL')
    data={k:(rtl/(k+'.sv')).read_bytes() for k in LOCK}
    if {k:sha256(v).hexdigest() for k,v in data.items()}!=LOCK: raise ValueError('wrong module set')
    src={k:v.decode() for k,v in data.items()}; out.mkdir(); cand=candidate(src['RenameStage']); wrapper=fixture(src)
    (out/'RenameStage.sv').write_bytes(cand.encode()); (out/'wiring.svh').write_bytes(wrapper.encode()); tb=HERE.parent/'tests/copy_load_rename_tb.v'
    mutations={
        'candidate':None,
        'omit_lane1':("copyload_hit_1 ? io_dec_uops_0_lrs2", "1'b0 ? io_dec_uops_0_lrs2", 'SOURCE_ORACLE_MISMATCH case=0 lane=1'),
        'ignore_copy_sfb':('!io_dec_uops_0_is_sfb && !io_dec_uops_1_is_sfb',"1'b1 && !io_dec_uops_1_is_sfb",'UNEXPECTED_SOURCE_CHANGE case=16 lane=1'),
        'original_map_read':('.io_map_reqs_1_lrs1        (copyload_eff_1)', '.io_map_reqs_1_lrs1        (io_dec_uops_1_lrs1)', 'SOURCE_ORACLE_MISMATCH case=0 lane=1'),
    }
    results={}
    for label,mutation in mutations.items():
        text=cand if mutation is None else once(cand,*mutation[:2])
        f=out/(label+'.sv'); f.write_bytes(once(text,'module RenameStage(','module RenameStageCopyLoad(').encode())
        exe=out/(label+'.vvp'); cmd=[cc]+(['-B',str(ivl)] if ivl else [])+['-g2012','-DSYNTHESIS','-s','tb','-I',str(out),'-o',str(exe),str(tb),str(f)]+[str(rtl/(k+'.sv')) for k in LOCK]
        subprocess.run(cmd,check=True,timeout=90); vp=subprocess.run([vvp,'-N']+(['-M',str(ivl)] if ivl else [])+[str(exe)],capture_output=True,text=True,timeout=90)
        log=vp.stdout+vp.stderr; (out/(label+'.txt')).write_text(log)
        if mutation is None:
            if vp.returncode or log.strip()!='COPYLOAD_RENAME_PASS cases=22': raise ValueError('candidate failed: '+log[:500])
        elif vp.returncode!=1 or log.strip()!=mutation[2]: raise ValueError('mutation escaped or failed unexpectedly: '+log[:500])
        results[label]='passed' if mutation is None else mutation[2]
    version=subprocess.run([cc]+(['-B',str(ivl)] if ivl else [])+['-V'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,check=True).stdout.splitlines()[0]
    return dict(simulator=version,directed_cases=22,scope='Directed paired rename-stage RTL only. No full-core equivalence, timing, speedup or board score.',module_sha256=LOCK,candidate_sha256=sha256(cand.encode()).hexdigest(),bench_sha256=sha256(tb.read_bytes()).hexdigest(),wiring_sha256=sha256(wrapper.encode()).hexdigest(),results=results)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rtl',type=Path);p.add_argument('out',type=Path)
    p.add_argument('--iverilog',default='iverilog');p.add_argument('--vvp',default='vvp');p.add_argument('--ivl',type=Path);a=p.parse_args()
    result=run(a.rtl,a.out,a.iverilog,a.vvp,a.ivl);(a.out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('PAIRED_RENAME_TEST_PASSED_NOT_FULL_CORE')
