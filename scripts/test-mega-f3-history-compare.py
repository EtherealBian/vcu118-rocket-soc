#!/usr/bin/env python3
"""Compare same-cycle F3 history and fetch-correction candidates on the sealed RTL.

Reads an immutable implementation kit; the derived full module and all tool
outputs go to a fresh, separate directory, never to the running implementation.
"""
import argparse
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess

SEAL = 'ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456'
LEAF = '5ba06d634a5d84720501b281b8adb406af68113ff105ef5fa39182077b7c0ffd'
F = 'f3_predicted_ghist_'
Q = '_f3_io_deq_bits_ghist_'
H = 'old_history'
FLAGS = ('new_saw_branch_not_taken', 'new_saw_branch_taken')
CORR = [f'_f3_correct_f{n}_ghist_T_4' for n in (1, 2)]
PRED = [f'_f3_bpd_resp_io_deq_bits_preds_{i}_taken' for i in range(8)]
CFI = ['_bpd_decoder'+suffix+'_io_out_cfi_type' for suffix in ('0','1','','_1','_2','0b','1_1','_3','_4','_5')]
INPUT = {**dict.fromkeys(PRED,1), **dict.fromkeys(CFI,3), 'f3_prev_is_half':1, 'f3_prev_half':16,
         '_f3_io_deq_bits_data':128, '_f3_io_deq_bits_mask':8, '_f3_io_deq_valid':1,
         '_f3_io_deq_bits_pc': 40, Q+'current_saw_branch_not_taken': 1,
         **{p+n: (64 if n==H else 1) for p in (Q, 's1_ghist_', 's2_ghist_') for n in (H, *FLAGS)},
         's1_vpc':40, 's2_vpc':40, 'f3_predicted_target':40, 's1_valid':1,'s2_valid':1,
         '_f4_io_enq_ready':1, 'io_cpu_sfence_valid':1, 'io_cpu_redirect_flush':1}
OUTPUT = {**dict.fromkeys(CORR,1), F+H:64, **dict.fromkeys([F+n for n in FLAGS],1),
          '_GEN_133':1, 'f2_clear':1, 'f4_io_enq_bits_cfi_idx_bits':3, 'f4_io_enq_bits_cfi_idx_valid':1,
          'f4_io_enq_bits_br_mask':8}

def check(test, why):
    if not test:
        raise ValueError(why)

def one(src, old, new):
    check(src.count(old)==1, 'expected one '+old)
    return src.replace(old, new)

def digest(data):
    return sha256(data).hexdigest()

def derive(src):
    base, shift, choose = 'vcu_f3_hist_base', 'vcu_f3_hist_shift_zero', 'vcu_f3_hist_use_shift'
    text = (f'  wire [63:0] {base} = {Q+FLAGS[1]} ? _GEN_123 : {Q+FLAGS[0]} ? _GEN_122 : {Q+H};\n'
            f"  wire [63:0] {shift} = {{{base}[62:0], 1'b0}};\n"
            f'  wire {choose} = ~{F}ignore_second_bank & {F}first_bank_saw_not_taken;\n')
    anchor = re.findall(r'^  wire +'+CORR[0]+r' = ', src, re.M)
    check(len(anchor)==1, 'missing correction anchor')
    src=one(src, anchor[0], text+anchor[0])
    for stage in (1,2):
        history=f's{stage}_ghist_old_history'; eq=history+' == '+F+H
        src=one(src, eq, f'({choose} ? ({history} == {shift}) : ({history} == {base}))')
    return src

def replace_rhs(src, net, value):
    # Change only the exact declaration, leaving every other consumer untouched.
    rx=r'(^  wire\s+(?:\[\d+:0\]\s+)?'+re.escape(net)+r' = )[^;\n]+;'
    out,n=re.subn(rx, lambda m:m[1]+value+';', src, flags=re.M)
    check(n==1,'missing or duplicate '+net); return out

def prefix(src):
    # For arbitrary (even non-onehot) redirects, count branches strictly before
    # the first redirect. A branch on that redirect goes in the taken flag.
    names=lambda group: '{'+', '.join(f'f3_{group}_{i}' for i in reversed(range(8)))+'}'
    rows=[f'  wire [7:0] vcu_f3_redir = {names("redirects")};', f'  wire [7:0] vcu_f3_branch = {names("br_mask")};']
    for bank in (0,1):
        # Local prefix, computed independently in both halves. If bank 0
        # redirects, the consuming mux already ignores bank 1 entirely.
        start=4*bank; local=[]; taken=[]
        for i in range(start,start+4):
            local.append(f'(vcu_f3_branch[{i}] & ~(|vcu_f3_redir[{i}:{start}]))')
            no_prev='' if i==start else f' & ~(|vcu_f3_redir[{i-1}:{start}])'
            taken.append(f'(vcu_f3_branch[{i}] & vcu_f3_redir[{i}]'+no_prev+')')
        for n, terms in [('not',local),('taken',taken)]:
            rows.append(f'  wire vcu_f3_b{bank}_{n} = '+ ' | '.join(terms)+';')
    marker=re.findall(r'^  wire +'+F+'cfi_in_bank_0 = ',src,re.M); check(len(marker)==1,'missing prefix anchor')
    src=one(src,marker[0],'\n'.join(rows)+'\n'+marker[0]); src=replace_rhs(src,F+'cfi_in_bank_0','|vcu_f3_redir[3:0]')
    src=replace_rhs(src,F+'first_bank_saw_not_taken', 'vcu_f3_b0_not | '+Q+'current_saw_branch_not_taken')
    src=replace_rhs(src,F+FLAGS[0],F+'ignore_second_bank ? '+F+'first_bank_saw_not_taken : vcu_f3_b1_not')
    src=replace_rhs(src,F+FLAGS[1],F+'ignore_second_bank ? vcu_f3_b0_taken : vcu_f3_b1_taken')
    base='('+Q+FLAGS[1]+' ? _GEN_123 : '+Q+FLAGS[0]+' ? _GEN_122 : '+Q+H+')'
    before=F+'ignore_second_bank ? '+base
    check(before in src,'unexpected stock history')
    rows=['  wire [63:0] vcu_f3_prefix_base = '+base+';', "  wire [63:0] vcu_f3_prefix_shift = {vcu_f3_prefix_base[62:0], 1'b0};"]
    marker=re.findall(r'^  wire \[63:0\] +'+F+H+r' = ',src,re.M); check(len(marker)==1,'missing history anchor')
    src=one(src,marker[0],'\n'.join(rows)+'\n'+marker[0]);return replace_rhs(src,F+H,'~'+F+'ignore_second_bank & '+F+'first_bank_saw_not_taken ? vcu_f3_prefix_shift : vcu_f3_prefix_base')

def eligible_lanes(src):
    # The original fetch masks exclude instructions after the first redirect.
    # Retain those masks and use the actual predictor direction. No one-hot
    # assumption is fed to SAT: the full lane eligibility producer is included.
    for bank in (0,1):
        for taken,name in [(False,'not'),(True,'taken')]:
            terms=[f'(f3_br_mask_{i} & '+('' if taken else '~')+PRED[i]+')' for i in range(4*bank,4*bank+4)]
            src=replace_rhs(src,f'vcu_f3_b{bank}_{name}', ' | '.join(terms))
    return src

def extract(src):
    # Start from the actual named results and follow their scalar/vector
    # declarations. A new dependency cannot turn into an implicit free input.
    decls={}; body=[]; seen=set()
    for row in src.splitlines():
        m=re.fullmatch(r'\s*(?:wire\s+(?:\[\d+:\d+\]\s*)?|assign\s+)(\w+)\s*=\s*([^;]+);\s*',row.split('//')[0])
        if m:
            check(m[1] not in decls, 'duplicate '+m[1]); decls[m[1]]=(row.split('//')[0].strip(),m[2])
    used=set()
    def add(n):
        if n in seen: return
        if n in INPUT:
            used.add(n); return
        check(n in decls,'no equation: '+n); line,expr=decls[n]
        for t in re.findall(r'\b[A-Za-z_]\w*',re.sub(r"\b\d+'[bdh][a-fA-F\d]+",'0',expr)):
            add(t)
        # An assign on a previously declared wire needs an explicit local wire.
        if line.startswith('assign '):
            decl=re.findall(r'^  wire\s+(\[\d+:\d+\]\s+)?'+re.escape(n)+r';',src,re.M)
            check(len(decl)==1,'missing declaration of '+n); body.append('wire '+decl[0]+n+';')
        body.append(line); seen.add(n)
    for n in OUTPUT: add(n)
    check(used==set(INPUT), 'unmatched cut inputs')
    width=lambda w: f'[{w-1}:0] ' if w>1 else ''
    ports=[f'input {width(w)}{n}' for n,w in INPUT.items()]+[f'output {width(w)}o{i}' for i,w in enumerate(OUTPUT.values())]
    return '\n'.join(['module top('+', '.join(ports)+');',*body,*[f'assign o{i} = {n};' for i,n in enumerate(OUTPUT)],'endmodule',''])

def levels(mod):
    pins=mod['ports']; drivers={}; types=Counter(); roots=set()
    for n,w in INPUT.items():
        p=pins[n]; check(p['direction']=='input' and len(p['bits'])==w, n); roots.update(p['bits'])
    check(len(roots)==sum(INPUT.values()),'input alias')
    for c in mod['cells'].values():
        kind=c['type']; types[kind]+=1; check(re.fullmatch(r'LUT[1-6]|MUXF[789]|INV|MUXCY|XORCY',kind),kind)
        ins=[]; outs=[]
        for port, bits in c['connections'].items():
            check(len(bits)==1, 'non-scalar primitive')
            (ins if c['port_directions'][port]=='input' else outs).extend(bits)
        check(ins and len(outs)==1 and outs[0] not in drivers and outs[0] not in roots,'bad drivers'); drivers[outs[0]]=ins
    groups={'all':roots, 'predicted_directions':{pins[n]['bits'][0] for n in PRED},
            'decoded_cfi':{b for n in CFI for b in pins[n]['bits']},
            's1_s2_old_histories':set(pins['s1_ghist_old_history']['bits']+pins['s2_ghist_old_history']['bits']),
            'f3_old_history':set(pins[Q+H]['bits'])}
    result={}; outs=[pins['o'+str(i)]['bits'] for i in range(len(OUTPUT))]; check([len(x) for x in outs]==list(OUTPUT.values()),'wrong outputs')
    for label, starts in groups.items():
        @lru_cache(None)
        def depth(bit):
            if bit in starts: return 0
            if bit in roots or bit in ('0','1'): return -10000
            check(bit in drivers,'undriven bit'); return 1+max(map(depth,drivers[bit]))
        ds=[max(map(depth,bs)) for bs in outs]; result[label]=[None if d<0 else d for d in ds]; depth.cache_clear()
    return dict(cells=dict(sorted(types.items())),total=sum(types.values()),primitive_depth_by_start=result)

def run(kit,out,yosys):
    raw=(kit/'rtl/BoomFrontend.sv').read_bytes(); seal=(kit/'CANDIDATE.sha256').read_bytes()
    check(digest(raw)==LEAF and digest(seal)==SEAL and (LEAF+'  rtl/BoomFrontend.sv').encode() in seal.splitlines(), 'kit mismatch')
    check(kit not in out.parents and out not in kit.parents and kit!=out,'output overlaps kit'); out.mkdir()
    abc=shutil.which('berkeley-abc'); check(abc,'missing ABC')
    ver=subprocess.check_output([str(yosys),'-V'],text=True).strip();check(ver=='Yosys 0.9 (git sha1 1979e0b)','unmatched tool')
    def invoke(label, cmds):
        (out/(label+'.ys')).write_text(cmds+'\n'); log=out/(label+'.log')
        with log.open('wb') as f: subprocess.run([str(yosys),'-Q','-T','-s',label+'.ys'],cwd=out,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
        return log.read_text()
    src=raw.decode(); candidate=derive(src); direct=prefix(src); both=derive(direct); mapped={}; proofs={}; cuts={}
    valid={'stock':src,'early_compare':candidate,'bank_prefix':direct,'prefix_and_compare':both,'eligible_lanes':eligible_lanes(direct),'lanes_and_compare':derive(eligible_lanes(direct))}
    for label,leaf in valid.items():
        if label!='stock': (out/(label+'-BoomFrontend.sv')).write_bytes(leaf.encode())
    for label,s in [*valid.items(), ('unmask_lane2',one(valid['eligible_lanes'], '(f3_br_mask_2 & ~'+PRED[2]+')', '(_f3_br_mask_2_T & ~'+PRED[2]+')')), ('drop_lane3_not_taken',one(direct,'(vcu_f3_branch[3] & ~(|vcu_f3_redir[3:0]))',"1'b0")), ('ignore_pc_boundary',one(candidate,'~'+F+'ignore_second_bank &','~'+F+'cfi_in_bank_0 &')),
                    ('swap_f2_shifted_operand',one(candidate,'s2_ghist_old_history == vcu_f3_hist_shift_zero','s1_ghist_old_history == vcu_f3_hist_shift_zero'))]:
        cut=extract(s); (out/(label+'.v')).write_bytes(cut.encode()); cuts[label]=digest(cut.encode())
        if label!='stock':
            log=invoke('prove-'+label, 'read_verilog -noautowire stock.v; rename top gold; read_verilog -noautowire '+label+'.v; rename top gate\nmiter -equiv -flatten gold gate compare; hierarchy -check -top compare; proc; opt; check -assert; sat -prove trigger 0 compare')
            good='SAT proof finished - no model found: SUCCESS!'; bad='SAT proof finished - model found: FAIL!'
            check((log.count(good),log.count(bad))==((1,0) if label in valid else (0,1)),label+' unexpected SAT decision'); proofs[label]='equivalent' if label in valid else 'counterexample'
        if label in valid:
            log=invoke('map-'+label,f'read_verilog -noautowire {label}.v\nsynth_xilinx -family xcup -flatten -top top\ncheck -assert; write_json {label}.json')
            check(log.count('Running ABC command: berkeley-abc -s -f <abc-temp-dir>/abc.script 2>&1')==1,'unexpected mapper')
            mapped[label]=levels(json.loads((out/(label+'.json')).read_bytes())['modules']['top'])
    return dict(scope='F3 history correction combinational cuts, binary inputs; isolated xcup primitive mapping, not routed timing, IPC, or board throughput.',kit_sha256=SEAL,stock_leaf_sha256=LEAF,derived_leaf_sha256={k:digest(v.encode()) for k,v in valid.items() if k!='stock'},yosys=ver,yosys_sha256=digest(yosys.read_bytes()),abc_sha256=digest(Path(abc).read_bytes()),cut_sha256=cuts,proofs=proofs,outputs=list(OUTPUT),mapping=mapped)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('kit',type=Path);ap.add_argument('out',type=Path);ap.add_argument('--yosys',type=Path,required=True);a=ap.parse_args()
    r=run(a.kit.resolve(),a.out.resolve(),a.yosys.resolve());(a.out/'result.json').write_bytes((json.dumps(r,indent=2)+'\n').encode());print(json.dumps(r['mapping'],indent=2))
