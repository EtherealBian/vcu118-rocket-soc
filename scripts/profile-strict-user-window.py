#!/usr/bin/env python3
"""Count the pinned Linux ELF's user instructions, never emulator time or FPGA scores."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ORACLE = runpy.run_path(str(ROOT / 'scripts/derive-target-length-crcs.py'))
CM = ORACLE['CM']
ELF = '61f7c4579b762f86d7d7dc93d4c385d08e50248f3dd6a8a9105fd5e88b58886a'
QEMU = '6c62c938d2c38e97a4853d94a65791723e9c282fb3bc8634951ae81f8d6d12f0'
PROFILE = 'g15-gc-lto-ooo-strict'
START_CALL, BEGIN, END, CLOCK = 0x106ac, 0x106b0, 0x10f3a, 0x147ac
LIST, NEXT = 0x13b0c, 0x10af0
CRC4 = {'performance': '0x9f95', 'validation': '0x19d9'}
ASM = re.compile(rb'^0x([0-9a-f]+):\s+([0-9a-f]{4}(?:[0-9a-f]{4})?)\s+')
EXEC = re.compile(rb'^Trace 0: 0x[0-9a-f]+ \[0000000000000000/([0-9a-f]{16})/0x6000\] *\n$')
SYMS = [(0x10180,0x11ca4,'main'), (0x11dac,0x11f92,'crcu16'),
        (0x11f92,0x12186,'core_state_transition'), (0x12186,LIST,'calc_func'),
        (LIST,0x1425c,'core_bench_list'), (0x146b0,CLOCK,'memset'), (0x14b58,0x14f98,'memcpy')]

def digest(p):
    return sha256(p.read_bytes()).hexdigest()

def group(op):
    op = op[2:] if op.startswith('c.') else op
    if op in 'lb lbu lh lhu lw lwu ld ldsp lwsp'.split(): return 'load'
    if op in 'sb sh sw sd swsp sdsp'.split(): return 'store'
    if op in 'beq bne blt bge bltu bgeu beqz bnez'.split(): return 'conditional_branch'
    if op in 'j jr jal jalr'.split(): return 'jump_call_return'
    if op in 'mul mulw'.split(): return 'multiply'
    if op in 'sll slli sllw slliw srl srli srlw srliw sra srai sraw sraiw'.split(): return 'shift'
    if op in 'and andi or ori xor xori'.split(): return 'bitwise'
    if op in 'add addi addiw addw addi16sp addi4spn sub subw lui auipc mv li slt slti sltu sltiu nop'.split(): return 'other_integer'
    raise ValueError('unclassified window instruction: '+op)

def disassemble(tool, elf, data):
    out = subprocess.check_output([tool,'-d','-M','no-aliases,numeric',elf],text=True)
    ops = {}
    for addr, word, op in re.findall(r'^\s*([0-9a-f]+):\s+([0-9a-f]{4}(?:[0-9a-f]{4})?)\s+(\S+)',out,re.M):
        pc=int(addr,16); length=len(word)//2
        if pc in ops or data[pc-0x10000:pc-0x10000+length] != int(word,16).to_bytes(length,'little'):
            raise ValueError('disassembly disagrees with pinned RX image')
        ops[pc] = word.encode(),length,op
    # NEXT is the target of the steady-state back edge.
    for pc,word in [(START_CALL,b'100040ef'),(END,b'073030ef'),(BEGIN,b'ec3e'),(NEXT,b'4585')]:
        if ops[pc][0]!=word: raise ValueError('changed loop or clock fences')
    return ops

class Window:
    def __init__(self, ops):
        self.ops=ops; self.phase=0; self.hist=Counter(); self.rounds=[]
        self.pcs=sha256(); self.buf=bytearray(); self.clock_entries=0; self.list_calls=[]
    def visit(self, pc):
        if pc == START_CALL:
            if self.phase!=0: raise ValueError('duplicate start clock call')
            self.phase=1
        elif pc == CLOCK:
            if (self.phase,self.clock_entries) not in ((1,0),(3,1)): raise ValueError('unexpected clock call')
            self.clock_entries+=1
        elif pc == BEGIN:
            if self.phase!=1 or self.clock_entries!=1: raise ValueError('missing start clock call/return')
            self.phase=2; self.rounds.append(0); self.list_calls.append(0)
        elif pc == END:
            if self.phase!=2: raise ValueError('unexpected stop clock call')
            self.phase=3
        if self.phase!=2: return
        if pc not in self.ops: raise ValueError('unknown PC in timed body')
        if pc==NEXT: self.rounds.append(0); self.list_calls.append(0)
        if pc==LIST: self.list_calls[-1]+=1
        self.rounds[-1]+=1; self.hist[pc]+=1; self.buf.extend(struct.pack('<I',pc))
        if len(self.buf)>=65536: self.pcs.update(self.buf); self.buf.clear()
    def finish(self):
        if self.phase!=3 or self.clock_entries!=2 or self.list_calls!=[2]*4:
            raise ValueError('incomplete timed window or wrong two-list-calls-per-round count')
        self.pcs.update(self.buf); self.buf.clear()
        functions,groups=Counter(),Counter(); compressed=0
        for pc,n in self.hist.items():
            names=[name for a,b,name in SYMS if a<=pc<b]
            if len(names)!=1: raise ValueError('unmapped user function: '+hex(pc))
            _,sz,op=self.ops[pc]; functions[names[0]]+=n; groups[group(op)]+=n
            if sz==2: compressed+=n
        return dict(dynamic_instructions=sum(self.rounds),by_round=self.rounds,compressed=compressed,
                    by_function=dict(sorted(functions.items())),by_kind=dict(sorted(groups.items())),
                    ordered_pc_sha256=self.pcs.hexdigest())

def trace(lines,ops,single):
    window=Window(ops); blocks={}; pending=[]
    for line in lines:
        if match:=ASM.match(line):
            pc=int(match[1],16)
            if pc not in ops or match[2]!=ops[pc][0] or (pending and pending[-1]+ops[pending[-1]][1]!=pc):
                raise ValueError('wrong opcode or noncontiguous translated block')
            pending.append(pc)
        elif match:=EXEC.fullmatch(line):
            pc=int(match[1],16)
            if pending:
                block=tuple(pending); pending=[]
                if block[0]!=pc or (single and len(block)!=1) or blocks.setdefault(pc,block)!=block:
                    raise ValueError('unexpected block shape')
            if pc not in blocks: raise ValueError('executed unknown translation block')
            for address in blocks[pc]: window.visit(address)
        elif line.strip() not in (b'',b'----------------',b'IN:'):
            raise ValueError('unexpected emulator trace line: '+repr(line[:80]))
    if pending: raise ValueError('trailing partial block')
    return window.finish()

def measure(qemu,elf,objdump):
    if digest(elf)!=ELF or digest(qemu)!=QEMU: raise ValueError('wrong ELF or QEMU user executable')
    data=elf.read_bytes(); ops=disassemble(objdump,elf,data); rows={}
    for name,(seed,*_) in CM['CASES'].items():
        pair=[]
        for single in (False,True):
            args=[qemu,'-cpu','rv64gcsu-v1.10.0','-d','in_asm,exec,nochain']
            if single: args+=['-singlestep']
            with tempfile.TemporaryFile() as out, subprocess.Popen(['timeout','180',*args,elf,seed,seed,'0x66','4','7','1','2000'],stdout=out,stderr=subprocess.PIPE) as child:
                try: row=trace(child.stderr,ops,single)
                finally: child.stderr.close()
                if child.wait()!=0: raise ValueError('emulator failed or timed out')
                out.seek(0); text=out.read().decode('ascii')
            final=ORACLE['crc'](text,name,4)
            if (final!=CRC4[name] or ORACLE['field'](text.splitlines(),'Compiler version')!='GCC15.1.0' or
                ' '.join(ORACLE['field'](text.splitlines(),'Compiler flags').split())!=CM['PROFILES'][PROFILE][1]):
                raise ValueError('oracle CRC or profile mismatch')
            pair.append(dict(row,crcfinal=final))
        if pair[0]!=pair[1]: raise ValueError('block-expansion and one-instruction traces differ')
        rows[name]=pair[0]
    return dict(scope='QEMU Linux-user, four iterations per seed, exact fixed ELF, one context, 2000 bytes. Guest user instructions only; neither CPU cycles nor board throughput.',
                elf_sha256=ELF,qemu_executable_sha256=QEMU,iterations_per_seed=4,results=rows)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('qemu',type=Path);p.add_argument('elf',type=Path);p.add_argument('objdump',type=Path);a=p.parse_args()
    print(json.dumps(measure(a.qemu.resolve(),a.elf.resolve(),a.objdump.resolve()),indent=2))
