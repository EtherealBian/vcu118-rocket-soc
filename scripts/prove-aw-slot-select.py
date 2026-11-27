#!/usr/bin/env python3
"""Prove and map a source-local AW slot decoder without modifying the board kit."""
import argparse
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess

TOP = 'AsyncQueueSource_AXI4BundleAW'
DEPS = ('AsyncValidSync', 'AsyncResetSynchronizerShiftReg_w4_d3_i0',
        'AsyncResetSynchronizerShiftReg_w1_d3_i0_2', 'AsyncResetSynchronizerPrimitiveShiftReg_d3_i0')
WIDTH = dict(id=4, addr=32, len=8, size=3, burst=2, lock=1, cache=4, prot=3, qos=4)
ROOT = Path(__file__).resolve().parents[1]


def require(condition, msg):
    if not condition: raise ValueError(msg)


def conditions(src):
    plain = re.sub(r'//[^\n]*', '', src)
    bank, = re.findall(r'always @\(posedge clock\) begin(.*?)\n  end\b', plain, re.S)
    found = re.findall(r'if \(([^\n]+)\) begin(.*?)\bend\b', bank, re.S)
    require(len(found) == 8, 'expected eight guarded payload words')
    for i, (_, body) in enumerate(found):
        writes = re.findall(r'\bmem_(\d+)_(\w+) <= io_enq_bits_(\w+);', body)
        require(writes == [(str(i), k, k) for k in WIDTH], 'wrong source or destination for a payload field')
    return [expr for expr, _ in found]


# Slots follow the low three bits' reflected-Gray order, not linear order.
SLOTS = tuple(b ^ (b >> 1) for b in range(8))


def ring_logic(fault=None):
    prev = {SLOTS[(i+1)%8]: slot for i, slot in enumerate(SLOTS)}
    if fault == 'bad_rotate': prev[3] = 0
    next_word = '{'+', '.join(f'aw_select[{prev[i]}]' for i in reversed(range(8)))+'}'
    initial = "8'h02" if fault == 'bad_reset' else "8'h01"
    return ("  reg [7:0] aw_select;\n  always @(posedge clock or posedge reset) begin\n"
            f"    if (reset) aw_select <= {initial};\n"
            "    else if (!_sink_valid_io_out) aw_select <= 8'h01;\n"
            f"    else if (_widx_T_1) aw_select <= {next_word};\n  end\n")


def lut_logic(fault=None):
    # LUT6 I[5:3] = valid, sink-valid, ready. I[2:0] is the binary pointer.
    lines = ['  wire [7:0] aw_ce;']
    for slot in range(8):
        index = SLOTS.index(slot)
        if fault == 'bad_init' and slot == 0:
            index ^= 1
        init = 1 << (56 + index)
        lines.append(f"  LUT6 #(.INIT(64'h{init:016x})) aw_slot_{slot} ("
                     f".O(aw_ce[{slot}]), .I0(widx_widx_bin[0]), .I1(widx_widx_bin[1]), "
                     ".I2(widx_widx_bin[2]), .I3(ready_reg), .I4(_sink_valid_io_out), .I5(io_enq_valid));")
    return '\n'.join(lines) + '\n'


def extra_logic(label):
    if label in ('ring', 'bad_rotate', 'bad_reset'):
        return ring_logic(label)
    if label in ('lut6', 'bad_init'):
        return lut_logic(label)
    return ''


def add_shadow(src, logic):
    pos = '  always @(posedge clock) begin'
    require(src.count(pos) == 1, 'ambiguous payload bank')
    return src.replace(pos, logic+pos)


def variants(src):
    by_slot = sorted(range(8), key=lambda b: b ^ (b >> 1))
    out = {}
    for label in ('binary', 'wrong_slot', 'ungated', 'ring', 'bad_rotate', 'bad_reset', 'lut6', 'bad_init'):
        ring = label in ('ring','bad_rotate','bad_reset')
        text = add_shadow(src, extra_logic(label))
        for i, cond in enumerate(conditions(src)):
            dec = i if label == 'wrong_slot' else by_slot[i]
            rhs = f"aw_select[{i}]" if ring else f"(widx_widx_bin[2:0] == 3'd{dec})"
            if label != 'ungated' or i != 0: rhs = '_widx_T_1 & '+rhs
            if label in ('lut6', 'bad_init'):
                rhs = f'aw_ce[{i}]'
            target = f'if ({cond}) begin'; require(text.count(target) == 1, 'unexpected select')
            text = text.replace(target, f'if ({rhs}) begin')
        out[label] = text
    return out


def instrument(stock, other, label):
    # Prove guards *from the two complete generated modules* on the original
    # pointer/handshake recurrence. Ring uses a reset base and inductive step;
    # binary and LUT6 require no init or input constraints after one source edge.
    ref, alt = conditions(stock), conditions(other)
    require(all(stock.count('if ('+x+') begin') == 1 for x in ref), 'ambiguous reference')
    check = other
    for a,b in zip(ref,alt): check = check.replace('if ('+b+') begin','if ('+a+') begin',1)
    ring = label in ('ring','bad_rotate','bad_reset')
    base = add_shadow(stock, extra_logic(label))
    require(check == base, 'variant changed something besides the eight guards and optional shadow')
    def packed(terms): return '{'+', '.join('('+x+')' for x in reversed(terms))+'}'
    sig = 'module '+TOP+'('; require(stock.count(sig) == 1, 'missing queue')
    invariant = ''
    if ring:
        spec = packed([f"(index == 3'd{i})" for i in range(8)])
        invariant = ' && (aw_select == '+spec+')'
    debug = ('  assign mask_a = '+packed(ref)+';\n  assign mask_b = '+packed(alt)+';\n'
             '  assign proof = (mask_a == mask_b) && (widx_gray == (widx_widx_bin ^ (widx_widx_bin >> 1)))'+invariant+';\n')
    unit = base.replace(sig,sig+'output proof, output [7:0] mask_a, mask_b,\n').replace('endmodule',debug+'endmodule')
    # Ignore payload values for the CE proof: the original registered writes
    # copy the exact same nine fields and observe none of the previous contents.
    unit += '\nmodule top(input clock, reset, io_enq_valid, io_async_safe_ridx_valid, io_async_safe_sink_reset_n, input [3:0] io_async_ridx, output proof, output [7:0] mask_a, mask_b);\n'
    ports = 'clock reset io_enq_valid io_async_safe_ridx_valid io_async_safe_sink_reset_n io_async_ridx proof mask_a mask_b'.split()
    return unit + TOP+' dut('+', '.join('.'+n+'('+n+')' for n in ports)+');\nendmodule\n'


def execute(tool, d, cmds, name="yosys.log"):
    with (d/name).open('xb') as f:
        subprocess.run([tool, '-Q', '-T', '-p', cmds], cwd=d, stdout=f, stderr=subprocess.STDOUT, check=True, timeout=120)
    return (d/name).read_text()


def topology(top, kind):
    parts = Counter(); owner = {}; ports = top['ports']; roots = {b for p in ports.values() if p['direction']=='input' for b in p['bits']}
    for c in top['cells'].values():
        typ=c['type']; parts[typ]+=1; con=c['connections']
        require(re.fullmatch(r'FD[CRPS]E|LUT[1-6]|MUXF[789]|INV|CARRY4|MUXCY|XORCY|BUFG',typ), 'unexpected primitive: '+typ)
        for p,d in c['port_directions'].items():
            if d != 'output': continue
            for bit in con[p]:
                require(isinstance(bit,int) and bit not in owner and bit not in roots, 'ambiguous driver')
                owner[bit] = c,p
    @lru_cache(None)
    def depth(bit):
        if bit in roots or bit in ('0','1'): return 0
        c,p=owner[bit]; typ=c['type']
        if typ.startswith('FD') and p=='Q': return 0
        require(re.fullmatch(r'LUT[1-6]|MUXF[789]|INV',typ), 'unexpected primitive on payload CE: '+typ)
        return 1+max(depth(b) for pin,d in c['port_directions'].items() if d=='input' for b in c['connections'][pin])
    ce=[]; used=set()
    for i in range(8):
        enables=set()
        for field,w in WIDTH.items():
            qs=ports[f'io_async_mem_{i}_{field}']['bits']; ds=ports['io_enq_bits_'+field]['bits']
            require(len(qs)==len(ds)==w, 'wrong mapped port width')
            for q, d in zip(qs,ds):
                c,p=owner[q]; con=c['connections']; require(c['type']=='FDRE' and p=='Q' and con['D']==[d] and con['R']==['0'] and con['C']==ports['clock']['bits'] and q not in used, 'payload bit not a direct unique D/Q register'); used.add(q); enables.add(con['CE'][0])
        require(len(enables)==1, 'not one enable per word'); ce.append(enables.pop())
    require(len(set(ce))==8 and len(used)==488, 'word alias or incomplete payload')
    names = top['netnames']
    ready, = names['ready_reg']['bits']; sink, = names['_sink_valid_io_out']['bits']
    valid, = ports['io_enq_valid']['bits']; pointer = names['widx_widx_bin']['bits'][:3]
    sources = {'ready_reg': ready, 'sink_valid_sync_out': sink, 'enqueue_valid': valid}
    pin_loads = Counter(b for c in top['cells'].values() for p, direction in c['port_directions'].items()
                        if direction == 'input' for b in c['connections'][p])
    def lut_inputs(bit, lut):
        cell, port = owner[bit]
        require(cell['type'] == lut and port == 'O', 'unexpected CE driver: '+cell['type'])
        return [cell['connections'][f'I{j}'][0] for j in range(int(lut[-1]))]
    last = {'stock': 'LUT6', 'binary': 'LUT5', 'ring': 'LUT3', 'lut6': 'LUT6'}[kind]
    shared = set()
    for i, bit in enumerate(ce):
        ins = lut_inputs(bit, last)
        if kind == 'lut6':
            require(ins == pointer+[ready, sink, valid], 'wrong LUT pin order')
            require(int(owner[bit][0]['parameters']['INIT'], 2) == 1 << (56+SLOTS.index(i)), 'wrong mapped slot INIT')
        else:
            select = (names['widx_gray']['bits'] if kind == 'stock' else pointer if kind == 'binary'
                      else [names['aw_select']['bits'][i]])
            rest = set(ins) - set(select) - {valid}
            require(len(rest) == 1 and set(ins) == rest | set(select) | {valid}, 'wrong select or valid inputs')
            intermediate, = rest
            require(set(lut_inputs(intermediate, 'LUT2')) == {ready, sink}, 'wrong upstream ready inputs')
            shared.add(intermediate)
    require(len(shared) == (0 if kind == 'lut6' else 1), 'unexpected shared LUT count')
    return dict(primitive_counts=dict(sorted(parts.items())), payload_direct_dq_bits=len(used),
                enable_logic_levels_by_slot=[depth(b) for b in ce], last_lut_per_slot=last,
                shared_ready_luts_on_enables=len(shared), direct_input_pin_loads={k: pin_loads[b] for k,b in sources.items()})


def vendor_truth(out, primitive, iverilog, vvp, ivl_dir):
    """Elaborate the same eight primitive instances with the external vendor model."""
    model = primitive.read_bytes()
    d = out/'vendor'; d.mkdir()
    tb = """`timescale 1ns/1ps
module top;
 reg [2:0] widx_widx_bin;
 reg ready_reg, _sink_valid_io_out, io_enq_valid;
 integer i, h, ptr, g, slot; reg [7:0] expected;
""" + lut_logic() + """
 initial begin
   for (h=0; h<2; h=h+1) for (i=0; i<64; i=i+1) begin
     {io_enq_valid,_sink_valid_io_out,ready_reg,widx_widx_bin}=i[5:0]; #1;
     ptr=h*8+(i&7); g=ptr^(ptr>>1); slot=(g&7)^((g>>3)<<2);
     expected=(i>=56) ? (8'h01<<slot) : 8'h00;
     if (aw_ce !== expected) $fatal(1, "slot mismatch");
   end
   $display("VENDOR_LUT_PASS 128 vectors"); $finish;
 end
endmodule
"""
    (d/'tb.sv').write_text(tb)
    args = ['-B', str(ivl_dir)] if ivl_dir else []
    subprocess.run([iverilog, *args, '-g2012', '-s', 'top', '-o', 'check.vvp', str(primitive), 'tb.sv'], cwd=d, check=True, timeout=30)
    args = ['-M', str(ivl_dir)] if ivl_dir else []
    text = subprocess.check_output([vvp, *args, 'check.vvp'], cwd=d, text=True, timeout=30)
    require(text.splitlines().count('VENDOR_LUT_PASS 128 vectors') == 1, 'missing vendor truth-table check')
    return dict(model_sha256=sha256(model).hexdigest(), distinct_binary_input_vectors=64, pointer_high_values=2,
                slots_checked_together=8)


def run(kit, out, tool, primitive, iverilog, vvp, ivl_dir):
    require(tool is not None, 'Yosys executable not found')
    anchor=json.loads((ROOT/'docs/perf-mega175-aw-physopt.json').read_bytes()); manifest=(kit/'CANDIDATE.sha256').read_bytes(); digest=lambda b:sha256(b).hexdigest()
    require(digest(manifest)==anchor['board_input_seal'], 'wrong physical input seal')
    src={}; ids={}
    for name in (TOP,)+DEPS:
        fn=name+'.sv'; b=(kit/'rtl'/fn).read_bytes(); expect,=re.findall(rb'^([a-f0-9]{64})  rtl/'+re.escape(fn.encode())+rb'$',manifest,re.M)
        require(digest(b)==expect.decode(), 'changed leaf: '+fn); src[name]=b.decode(); ids[fn]=digest(b)
    require(ids[TOP+'.sv']==anchor['rtl_sha256'][TOP+'.sv'], 'different placed AW leaf')
    version=subprocess.check_output([tool,'-V'],text=True).strip(); abc=shutil.which('berkeley-abc')
    require(version=='Yosys 0.9 (git sha1 1979e0b)' and abc, 'unexpected mapper toolchain')
    out.mkdir(); truth=vendor_truth(out, primitive, iverilog, vvp, ivl_dir); stock=src[TOP]; variants_=variants(stock); maps={}; proofs={}
    for task, leaf in [('proof-'+n, instrument(stock,v,n)) for n,v in variants_.items()]+[('stock',stock),('binary',variants_['binary']),('ring',variants_['ring']),('lut6',variants_['lut6'])]:
        d=out/task; d.mkdir(); (d/'leaf.sv').write_bytes(leaf.encode()); (d/'deps.sv').write_bytes('\n'.join(src[n] for n in DEPS).encode()); read='read_verilog -DSYNTHESIS -sv deps.sv leaf.sv; '
        if task.startswith('proof-'):
            name = task[6:]
            if name in ('lut6', 'bad_init'):
                read = 'read_verilog +/xilinx/cells_sim.v; '+read
            read += 'hierarchy -check -top top; proc; flatten; opt; async2sync; opt; check -assert; '
            passes = {'unconditional': 'sat -seq 2 -prove-skip 1',
                      'reset': 'sat -seq 1 -set reset 1',
                      'step': 'sat -seq 2 -set-at 1 proof 1 -prove-skip 1'}
            kinds = ('reset','step') if name=='ring' else ('reset',) if name=='bad_reset' else ('step',) if name=='bad_rotate' else ('unconditional',)
            proofs[name] = {}
            for kind in kinds:
                cmd = passes[kind]+' -prove proof 1 -show mask_a -show mask_b'
                text = execute(tool,d,read+cmd,kind+'.log')
                if name in ('binary','ring','lut6'):
                    require(text.splitlines().count('SAT proof finished - no model found: SUCCESS!')==1,'guard or pointer invariant failed')
                    proofs[name][kind] = 'proved'
                else:
                    require(text.splitlines().count('SAT proof finished - model found: FAIL!')==1,'missing counterexample')
                    if name in ('wrong_slot','ungated','bad_init'):
                        masks=[int(re.findall(r'^\s*2\s+\\'+n+r'\s+(\d+)\s+',text,re.M)[0]) for n in ('mask_a','mask_b')]
                        require(masks[0]!=masks[1], 'not a slot counterexample')
                    proofs[name][kind] = 'counterexample'
        else:
            if task == 'lut6':
                read = 'read_verilog -lib +/xilinx/cells_sim.v; '+read
            execute(tool,d,read+'hierarchy -check -top '+TOP+'; synth_xilinx -family xcup -flatten -top '+TOP+' -run begin:map_luts; select '+TOP+'; write_ilang -selected split.il', 'lower.log')
            text=execute(tool,d,'read_verilog -lib +/xilinx/cells_sim.v; read_ilang split.il; synth_xilinx -family xcup -top '+TOP+' -run map_luts:; check -assert; write_json mapped.json')
            require('Running ABC command: berkeley-abc ' in text, 'mapper was not run'); maps[task]=topology(json.loads((d/'mapped.json').read_bytes())['modules'][TOP],task);maps[task]['leaf_sha256']=digest(leaf.encode())
    result=dict(scope='Source-side AW word select only. Two-state guard proof and isolated xcup technology mapping, not routed timing, CDC signoff, or a benchmark.', board_input_seal=digest(manifest),input_sha256=ids,yosys=version,yosys_sha256=digest(Path(tool).read_bytes()),abc_sha256=digest(Path(abc).read_bytes()),vendor_truth=truth,proofs=proofs,maps=maps)
    (out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode()); return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('kit',type=Path); ap.add_argument('out',type=Path); ap.add_argument('--yosys',default='yosys')
    ap.add_argument('--unisim-lut6', type=Path, required=True); ap.add_argument('--iverilog', default='iverilog')
    ap.add_argument('--vvp', default='vvp'); ap.add_argument('--ivl-dir', type=Path); a=ap.parse_args()
    print(json.dumps(run(a.kit.resolve(), a.out.resolve(), shutil.which(a.yosys), a.unisim_lut6.resolve(),
                         a.iverilog, a.vvp, a.ivl_dir), indent=2))
