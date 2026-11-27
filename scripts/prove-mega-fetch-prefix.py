#!/usr/bin/env python3
"""Test pairwise prefix rotations in the sealed four-wide BOOM fetch buffer, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

TOPOLOGY = runpy.run_path(str(Path(__file__).with_name('map-mega-issue-cut.py')))['topology']
KIT = 'b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'
UNIT = 'a3c9510a0ac9c8f2ec7dd2bf3ff849adde8581c6847b181f22d7f7cec5a047dc'
PINS = ((12, 12), (24, 25), (11, 25), (23, 25))
YOSYS = 'f58d1dfcbc9b48a81357283e93b53e4c78415f6d28f227f0db34a79f316e6a64'
ABC = '6b6d93004494101bed191ddf29c411df55c50f990d7db56796767a3efbb03b09'


def need(ok, msg):
    if not ok:
        raise ValueError(msg)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def idx(i):
    return 'enq_idxs_'+str(i) if i else 'tail'


def rewrite(src, indices):
    for i in indices:
        need(i in range(2, 8), 'two preceding lanes required')
        a, b, v = 'in_mask_'+str(i-2), 'in_mask_'+str(i-1), idx(i-2)
        old = f'wire [31:0] {idx(i)} = {b} ? _GEN_{i} : {idx(i-1)};'
        # All three selectors depend on masks alone. They select rotates of the
        # *same* preceding prefix: zero, one, or two positions respectively.
        rhs = f'({{32{{~({a} | {b})}}}} & {v}) | ({{32{{{a} ^ {b}}}}} & {{{v}[30:0], {v}[31]}}) | ({{32{{{a} & {b}}}}} & {{{v}[29:0], {v}[31:30]}})'
        need(src.count(old) == 1, 'unexpected prefix site '+str(i))
        src = src.replace(old, old.split(' = ')[0]+' = '+rhs+';')
    return src


def logic(src, select):
    lines = re.findall(r'^  (wire\s+(?:\[31:0\]\s+)?(\w+) = [^;\n]+;)', src, re.M)
    found = [line for line, name in lines if name in select]
    need(len(found) == len(select) and {name for _, name in lines} >= select, 'missing or repeated cone equation')
    return '\n'.join(found)


def prefix(src, name):
    nets = {f'in_mask_{i}' for i in range(8)} | {idx(i) for i in range(1, 8)} | {f'_GEN_{i}' for i in range(1, 8)}
    # Expose all rewritten signals as well as all one-step rotations consumed by
    # the untouched tail update. No assumptions on reset, legal tail, or masks.
    outputs = [idx(i) for i in range(1, 8)] + [f'_GEN_{i}' for i in range(1, 8)]
    return (f'module {name}(input [31:0] tail,input io_enq_valid,input [7:0] io_enq_bits_mask,output [447:0] observation);\n'
            +logic(src, nets)+'\nassign observation = {'+', '.join(outputs)+'};\nendmodule\n')


def stock_chains(src):
    text = re.sub(r'//[^\n]*', '', src)
    # Capture the complete if / else-if chains, not adjacent GEN numbers inferred
    # from slot order. All instruction writers are the first body statement.
    row = r'^    (if|else if) \((_GEN_\d+)\) begin\s*\n      fb_uop_ram_(\d+)_inst <= (io_enq_bits_exp_insts_(\d+));'
    found = re.findall(row, text, re.M)
    need(len(found) == len(re.findall(r'fb_uop_ram_\d+_inst\s*<=', text)) == 256, 'missing instruction writer')
    chains = []
    for j in range(32):
        entries = found[8*j:8*j+8]
        for k, (keyword, sel, slot, data, lane) in enumerate(entries):
            need((keyword, int(slot), int(lane), sel) == ('else if' if k else 'if', j, 7-k, f'_GEN_{9+33*(7-k)+j}'), 'changed instruction priority')
        chains.append(entries)
    return chains



def masked(src, local_select=False):
    chains = stock_chains(src)
    for j, chain in enumerate(chains):
        ce = ' | '.join(sel for _,sel,_,_,_ in chain)
        gate = re.compile(rf'^    if \({re.escape(ce)}\) begin[^\n]*\n(?=      fb_uop_ram_{j}_ftq_idx <= io_enq_bits_ftq_idx;)', re.M)
        # The data pin is irrelevant when CE is low. On a write, do_enq and
        # io_enq_valid are both true; the local variant can omit them from the
        # final per-lane selector without changing the original write enable.
        terms = []
        for _,sel,_,data,lane in chain:
            if local_select:
                sel = f'(io_enq_bits_mask[{lane}] & {idx(int(lane))}[{j}])'
            terms.append('({32{'+sel+'}} & '+data+')')
        expr = ' | '.join(terms)
        src, n = re.subn(rf'^      fb_uop_ram_{j}_inst <= io_enq_bits_exp_insts_\d;[^\n]*\n', '', src, flags=re.M)
        need(n==8, 'wrong number of old writers')
        src,n = gate.subn(lambda m:m[0]+f'      fb_uop_ram_{j}_inst <= {expr};\n',src)
        need(n==1, 'missing shared write-enable')
    return src


def masked_body(src, width):
    text = re.sub(r'//[^\n]*', '', src)
    rows = re.findall(r'^    if \(([^\n()]+)\) begin\s*\n      fb_uop_ram_(\d+)_inst <= ([^;\n]+);', text, re.M)
    need(len(rows)==len(re.findall(r'fb_uop_ram_\d+_inst\s*<=',text))==32, 'missing masked write')
    out=[]
    for j,(ce,slot,rhs) in enumerate(rows):
        need(int(slot)==j and rhs.count('{32{')==8, 'changed masked write shape')
        out.append(f'  if ({ce}) slot{j} <= '+rhs.replace('{32{','{'+str(width)+'{')+';')
    return out


def tail_block(src):
    text = re.sub(r'//[^\n]*','',src)
    blocks=re.findall(r'^    (if \(reset\) begin\s*\n      head <=.*?^    end)\s*\n  end\s*\n  `ifdef ENABLE_INITIAL_REG_',text,re.M|re.S)
    need(len(blocks)==1 and len(re.findall(r'\btail <=',blocks[0]))==10, 'unexpected tail update')
    body = re.sub(r'(?m)^\s*if \(do_deq\)\s*\n\s*head <= [^;]+;', '', blocks[0])
    body = re.sub(r'(?m)^\s*(?:head|maybe_full) <= [^;]+;', '', body)
    return 'always @* begin\n  tn = tail;\n'+body.replace('tail <=','tn =')+'\nend'


def invariant(src):
    select = {f'in_mask_{i}' for i in range(8)} | {idx(i) for i in range(1,8)} | {f'_GEN_{i}' for i in range(1,8)}
    return ('module top(input [31:0] any_tail,input [4:0] position,input use_any,input reset,input io_clear,input do_enq,'
            'input io_enq_valid,input [7:0] io_enq_bits_mask,output init_ok,output step_ok);\n'
            'wire [31:0] tail = use_any ? any_tail : (32\'h1 << position); reg [31:0] tn;\n'+logic(src,select)+'\n'+tail_block(src)+
            "\nassign init_ok = ~(reset | io_clear) | (tn == 32'h1);\nassign step_ok = (|tn) & ((tn & (tn-32'd1))==0);\nendmodule\n")


def state_cut(unit, masked_mode, name, arbitrary):
    pins='input [31:0] tail' if arbitrary else 'input [4:0] position'
    line='' if arbitrary else "wire [31:0] tail = 32'h1 << position;\n"
    rows=(masked_body(unit,1) if masked_mode else [f'  {kw} ({sel}) slot{j} <= {data};' for j,chain in enumerate(stock_chains(unit)) for kw,sel,_,data,_ in chain])
    text=(f'module {name}({pins},input do_enq,input io_enq_valid,input [7:0] io_enq_bits_mask,input [7:0] lanes,input [31:0] prior,output [31:0] updated);\n'+line)
    sel={f'in_mask_{i}' for i in range(8)} | {idx(i) for i in range(1,8)} | {f'_GEN_{i}' for i in range(1,272)}
    text+=logic(unit,sel)+'\n'+'\n'.join(f'wire io_enq_bits_exp_insts_{i}=lanes[{i}];' for i in range(8))+'\n'
    text+='\n'.join(f'reg slot{j}; assign updated[{j}]=slot{j};' for j in range(32))+'\nalways @* begin\n'
    return text+'\n'.join(f'  slot{j} = prior[{j}];' for j in range(32))+'\n'+'\n'.join(r.replace(' <= ',' = ') for r in rows)+'\nend\nendmodule\n'


def decision(log, ok):
    need(log.count('SAT proof finished - no model found: SUCCESS!')==int(ok) and log.count('SAT proof finished - model found: FAIL!')==int(not ok), 'unexpected SAT decision')


def clocked(src, bits, masked_mode=False):
    # The selected bits of all 32 instruction registers are retained as outputs,
    # with exact write order, independent lane data, and original enqueue capacity.
    nets = ({'do_enq'} | {f'in_mask_{i}' for i in range(8)} | {idx(i) for i in range(1, 8)} |
            {f'_GEN_{i}' for i in range(1, 272)})
    pins = ['input clock','input [31:0] tail','input [7:0] head','input maybe_full',
            'input io_enq_valid','input [7:0] io_enq_bits_mask']
    pins += [f'input [{len(bits)-1}:0] io_enq_bits_exp_insts_{i}' for i in range(8)]
    pins += [f'output reg [{len(bits)-1}:0] slot{j}' for j in range(32)]
    body = [logic(src, nets), 'always @(posedge clock) begin']
    if masked_mode:
        body += masked_body(src,len(bits))
    else:
        for j, chain in enumerate(stock_chains(src)):
            body += [f'  {kw} ({sel}) slot{j} <= {data};' for kw, sel, _, data, _ in chain]
    return 'module top('+',\n'.join(pins)+');\n'+'\n'.join(body)+'\nend\nendmodule\n'


def profile(top, bits):
    ports = top['ports']; flip = {}; cells = {}
    for name, c in top['cells'].items():
        if c['type'] != 'FDRE':
            cells[name] = c
            continue
        w = c['connections']
        need(set(w) == {'C','CE','D','Q','R'} and w['C'] == ports['clock']['bits'] and w['R'] == ['0'] and
             all(len(p)==1 for p in w.values()) and w['Q'][0] not in flip, 'unexpected mapped register')
        flip[w['Q'][0]] = (w['D'][0], w['CE'][0])
    ins = {k:v for k,v in ports.items() if v['direction']=='input'}
    expected = dict(clock=1, tail=32, head=8, maybe_full=1, io_enq_valid=1, io_enq_bits_mask=8,
                    **{f'io_enq_bits_exp_insts_{i}':len(bits) for i in range(8)})
    inbits = [b for p in ins.values() for b in p['bits']]
    need({k:len(v['bits']) for k,v in ins.items()}==expected and len(set(inbits))==len(inbits) and all(type(b) is int for b in inbits), 'changed mapped input boundary')
    need(all(len(ports[f'slot{j}']['bits'])==len(bits) for j in range(32)), 'wrong mapped output width')
    allq = [(j,b,q) for j in range(32) for b,q in zip(bits,ports[f'slot{j}']['bits'])]
    need(set(ports)-set(ins)=={f'slot{j}' for j in range(32)} and len(allq)==len(flip)==len(bits)*32 and
         {q for _,_,q in allq}==set(flip), 'missing mapped Q')
    outputs = {'all_D':[flip[q][0] for _,_,q in allq], 'all_CE':[flip[q][1] for _,_,q in allq]}
    for j,b,q in allq:
        if (j,b) in PINS:
            outputs[f'slot{j}_bit{b}_D'] = [flip[q][0]]
    boundary = dict(ins, **{k:{'direction':'output','bits':v} for k,v in outputs.items()})
    stats = TOPOLOGY({'ports':boundary,'cells':cells}, {k:len(v) for k,v in outputs.items()}, allow_muxcy=True)
    return dict(fdre=len(flip), comb=stats)


def run(kit, out, tool, full):
    lock = (kit/'CANDIDATE.sha256').read_bytes(); raw = (kit/'rtl/FetchBuffer.sv').read_bytes()
    need(sha(lock)==KIT and sha(raw)==UNIT and (UNIT+'  rtl/FetchBuffer.sv').encode() in lock.splitlines(), 'different board input')
    abc = shutil.which('berkeley-abc'); need(abc and sha(Path(abc).read_bytes())==ABC and sha(Path(tool).read_bytes())==YOSYS, 'unexpected mapper')
    out.mkdir(mode=0o700); src = raw.decode(); bits = list(range(32)) if full else [12,25]
    groups = {'pair_even':[2,4,6], 'pair_all':list(range(2,8))}
    variants = {'stock':src, **{k:rewrite(src,ix) for k,ix in groups.items()}}
    variants['onehot'] = masked(src)
    variants['onehot_local'] = masked(src,local_select=True)
    variants['pair_all_onehot'] = masked(variants['pair_all'])
    bad = variants['pair_even'].replace('tail[31:30]', 'tail[30:29]', 1)
    need(bad != variants['pair_even'], 'mutant not injected'); records = {}
    mislane = variants['onehot'].replace('({32{_GEN_240}} & io_enq_bits_exp_insts_7)', '({32{_GEN_240}} & io_enq_bits_exp_insts_6)',1)
    need(mislane!=variants['onehot'], 'data mutation absent')
    for name,unit in list(variants.items())+[('wrong_wrap',bad),('wrong_lane',mislane),('no_tail_invariant',variants['onehot'])]:
        d = out/name; d.mkdir(); info = dict(source_sha256=sha(unit.encode())); records[name] = info
        def yosys(command, log):
            p = d/log
            with p.open('xb') as f:
                subprocess.run([tool,'-Q','-T','-p',command],cwd=d,stdout=f,stderr=subprocess.STDOUT,timeout=360,check=True)
            return p.read_text()
        masked_mode = name in ('onehot','onehot_local','pair_all_onehot','wrong_lane','no_tail_invariant')
        if name=='stock':
            (d/'induction.v').write_text(invariant(src)); prep='read_verilog -noautowire induction.v; prep -top top; check -assert; '
            for prop, use_any in [('init_ok',1),('step_ok',0)]:
                decision(yosys(prep+f'sat -set use_any {use_any} -prove {prop} 1 top',prop+'.log'),True)
                info[prop]='proved'
        if masked_mode:
            arbitrary = name=='no_tail_invariant'
            (d/'gold.v').write_text(state_cut(src,False,'gold',arbitrary)); (d/'gate.v').write_text(state_cut(unit,True,'gate',arbitrary))
            cmd='read_verilog -noautowire gold.v gate.v; proc; miter -equiv -flatten gold gate m; hierarchy -top m; opt; check -assert; sat -prove trigger 0 -show-inputs -show-outputs m'
            ok = name in variants; decision(yosys(cmd,'store-proof.log'),ok)
            info['single_bit_all_slots_equivalence']='proved' if ok else 'counterexample'
        elif name != 'stock':
            (d/'gold.v').write_text(prefix(src,'gold')); (d/'gate.v').write_text(prefix(unit,'gate'))
            log = yosys('read_verilog -noautowire gold.v gate.v; miter -equiv -flatten gold gate m; hierarchy -top m; opt; check -assert; sat -prove trigger 0 -show-inputs -show-outputs m','proof.log')
            ok = name in groups
            decision(log,ok)
            info['prefix_equivalence'] = 'proved' if ok else 'counterexample'
        if name in variants:
            cut = clocked(unit,bits,masked_mode); (d/'cut.v').write_text(cut); info['cut_sha256']=sha(cut.encode())
            (d/'FetchBuffer.sv').write_bytes(unit.encode())
            yosys('read_verilog -sv -noautowire FetchBuffer.sv; hierarchy -check -top FetchBuffer; proc; check -assert','unit-check.log')
            info['full_unit_elaboration']='checked'
            log = yosys('read_verilog -noautowire cut.v; hierarchy -check -top top; proc; check -assert; synth_xilinx -family xcup -top top -flatten; check -assert; write_json mapped.json','map.log')
            need([s for s in log.splitlines() if s.startswith('Running ABC command:')] == ['Running ABC command: berkeley-abc -s -f <abc-temp-dir>/abc.script 2>&1'], 'unexpected ABC invocation')
            info['map']=profile(json.loads((d/'mapped.json').read_bytes())['modules']['top'],bits)
    result = dict(scope='Unplaced xcup instruction-write cone, including enqueue capacity and 32 slot write enables. Omits other payload fields, registered tail update, dequeue logic and actual routing. SAT compares 448 prefix/rotation bits for arbitrary two-state tails; masked data writes are proved for all 32 slots (bitwise, independent lanes/old state) under a separately proved one-hot tail after reset or clear. Not whole-core timing.',board_input_seal=KIT, instruction_bits=bits, yosys_sha256=YOSYS, abc_sha256=ABC, profiles=records)
    (out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--yosys',default='yosys');p.add_argument('--full',action='store_true');a=p.parse_args(); t=shutil.which(a.yosys);need(t,'Yosys not found');run(a.kit.resolve(),a.out.resolve(),t,a.full)
