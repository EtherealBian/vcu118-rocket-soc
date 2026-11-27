#!/usr/bin/env python3
"""Count the unmodified 24,000-round ELF workload, without timing the emulator."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import runpy
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
W = runpy.run_path(str(ROOT / 'scripts/profile-strict-user-window.py'))
SRC = 'd3481d4108ce211a053ef15be69af1bdd9dde1510fda80d92be0f6c3e98768f0'
HEADER = '0a0eed076b985a20a85980d5bb179df368e836acf155c32e38535ae540039a3f'
LOOP = {0x13b60: ('entry_jump', b'a011'), 0x13b62: ('copy', b'843a'),
        0x13b64: ('load', b'6018'), 0x13b6a: ('branch', b'ff65'), 0x13b6c: ('exit_pc', b'cbc1')}


def need(ok, why):
    if not ok:
        raise ValueError(why)


def parse(text, ops, n, mode):
    lines = text.splitlines(); rounds = []; hist = Counter()
    need(lines and lines[-1] == 'DONE', 'unfinished window')
    for line in lines[:-1]:
        r = re.fullmatch(r'R ([1-9][0-9]*) ([1-9][0-9]*)', line)
        if r:
            need(not hist and int(r[1]) == len(rounds)+1 <= n, 'round order')
            rounds.append(int(r[2])); continue
        need(len(rounds) == n and re.fullmatch(r'S [1-9][0-9]*(?: [0-9a-f]+)+', line), 'bad span')
        _, hits, *pcs = line.split(); pcs = [int(p,16) for p in pcs]
        need(mode in ('span','insn') and (mode != 'insn' or len(pcs) == 1), 'not one instruction')
        need(all(p in ops for p in pcs) and all(p + ops[p][1] == q for p,q in zip(pcs,pcs[1:])), 'unknown or noncontiguous PCs')
        for p in pcs:
            hist[p] += int(hits)
    need(len(rounds) == n and sum(rounds) == sum(hist.values()) and hist, 'round/PC total differs')
    need(hist[W['BEGIN']] == 1 and hist[W['NEXT']] == n-1 and hist[W['LIST']] == 2*n and
         all(not hist[p] for p in (W['START_CALL'], W['END'], W['CLOCK'])), 'wrong timed fences or list count')
    return rounds, hist


def classify(ops, hist):
    funcs, kinds = Counter(), Counter(); compressed = 0
    for p, hits in hist.items():
        matches = [name for a,b,name in W['SYMS'] if a <= p < b]; need(len(matches) == 1,'unmapped function')
        funcs[matches[0]] += hits; kinds[W['group'](ops[p][2])] += hits
        if ops[p][1] == 2: compressed += hits
    return dict(compressed=compressed,by_function=dict(sorted(funcs.items())),by_kind=dict(sorted(kinds.items())))


def compare(pair):
    need(len(pair) == 2 and pair[0] == pair[1], 'instruction and span measurements disagree')
    return pair[0]


def summarize(ops, rounds, hist, short, crc):
    need(all(ops[p][0] == word for p,(_,word) in LOOP.items()), 'changed reversal loop')
    rev = {name:hist[p] for p,(name,_) in LOOP.items()}
    need(0 < rev['entry_jump'] == rev['exit_pc'] and rev['copy'] + rev['entry_jump'] == rev['load'] == rev['branch'], 'reversal loop inventory')
    total = sum(rounds); small = sum(short.values()); union = hist.keys() | short.keys()
    # Total variation between normalized per-PC count distributions, in parts per million.
    delta = sum(abs(hist[p]*small - short[p]*total) for p in union)
    return dict(dynamic_user_instructions=total, round_min=min(rounds), round_max=max(rounds),
                ordered_round_counts_sha256=sha256(b''.join(struct.pack('<Q',x) for x in rounds)).hexdigest(),
                pc_histogram_sha256=sha256(b''.join(struct.pack('<IQ',p,hist[p]) for p in sorted(hist))).hexdigest(),
                distinct_pcs=len(hist), dynamic_instructions_at_pcs_absent_from_four_rounds=sum(hist[p] for p in hist if p not in short),
                four_round_pc_mix_total_variation_ppm=round(1000000*delta/(2*total*small),3),
                reversal_loop_pc_counts=rev, **classify(ops,hist), crcfinal=crc)


def measure(qemu, plugin, elf, objdump, private):
    need(W['digest'](elf) == W['ELF'], 'wrong release ELF')
    ops = W['disassemble'](objdump,elf,elf.read_bytes())
    original = json.loads((ROOT/'docs/perf-strict-user-window.json').read_bytes())
    oracle = json.loads((ROOT/'docs/coremark-target-length-crcs.json').read_bytes())['final_crc_by_iterations']['24000']
    env = {k:v for k,v in os.environ.items() if not k.startswith(('VCU_WINDOW_','QEMU_'))}
    results = {}
    for name,(seed,*_) in W['CM']['CASES'].items():
        for n in (4,24000):
            pair=[]; expected=original['results'][name] if n == 4 else None
            for mode in ('span','insn'):
                work=private/f'{name}-{n}-{mode}'; work.mkdir()
                p=subprocess.run(['nice','-n','17',qemu,'-cpu','rv64gcsu-v1.10.0','-plugin',plugin,elf,seed,seed,'0x66',str(n),'7','1','2000'],
                                 cwd=work, env=dict(env,VCU_WINDOW_MODE=mode,VCU_WINDOW_ROUNDS=str(n)),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=420)
                need(not p.stderr,'unexpected QEMU diagnostic'); out=p.stdout.decode('ascii')
                crc=W['ORACLE']['crc'](out,name,n); field=W['ORACLE']['field']
                need(crc == (expected['crcfinal'] if expected else oracle[name]) and field(out.splitlines(),'Compiler version') == 'GCC15.1.0' and
                     ' '.join(field(out.splitlines(),'Compiler flags').split()) == W['CM']['PROFILES'][W['PROFILE']][1], 'CRC/compiler mismatch')
                rounds,hist=parse((work/'counts.txt').read_text(),ops,n,mode)
                stream=work/'short.pcs'
                if expected:
                    need(stream.stat().st_size == 4*sum(rounds) and W['digest'](stream) == expected['ordered_pc_sha256'] and
                         expected['by_round'] == rounds and expected['dynamic_instructions'] == sum(rounds) and
                         all(expected[k] == v for k,v in classify(ops,hist).items()), 'four-round independent trace mismatch')
                else: need(not stream.exists(),'unexpected long PC stream')
                pair.append((rounds,hist))
            rounds,hist=compare(pair)
            if expected: short=hist
            else: results[name]=summarize(ops,rounds,hist,short,crc)
    return dict(scope='QEMU Linux-user instruction workload only. No cycles, elapsed times, FPGA clock or board throughput.',
                elf_sha256=W['ELF'],qemu_4_2_source_archive_sha256=SRC,qemu_plugin_header_sha256=HEADER,
                contexts=1,total_buffer_bytes=2000,iterations_per_seed=24000,results=results)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('source_archive',type=Path); p.add_argument('elf',type=Path); p.add_argument('objdump',type=Path); args=p.parse_args()
    archive,elf,objdump=(x.resolve() for x in (args.source_archive,args.elf,args.objdump))
    need(W['digest'](archive) == SRC and W['digest'](elf) == W['ELF'],'wrong QEMU source archive or target ELF')
    with tempfile.TemporaryDirectory(prefix='strict-target-count-') as root:
        d=Path(root); src=d/'src'; obj=d/'obj'; src.mkdir(); obj.mkdir()
        subprocess.run(['tar','-xf',archive,'--strip-components=1','-C',src],check=True)
        inc=src/'include/qemu'; need(W['digest'](inc/'qemu-plugin.h') == HEADER,'wrong plugin header')
        with (d/'build.log').open('w+') as log:
            try:
                for cmd in ([src/'configure','--target-list=riscv64-linux-user','--enable-plugins','--disable-system','--disable-docs','--disable-tools','--disable-guest-agent','--disable-werror','--disable-capstone'],
                            ['nice','-n','17','make','-j1'], ['cc','-std=c11','-O2','-fPIC','-Wall','-Wextra','-Werror','-fvisibility=hidden','-shared','-I',inc,ROOT/'scripts/strict-target-count.c','-o',d/'count.so']):
                    subprocess.run(cmd,cwd=obj,stdout=log,stderr=subprocess.STDOUT,check=True)
            except subprocess.CalledProcessError:
                log.seek(0); raise RuntimeError('private tool build failed:\n'+''.join(log.readlines()[-20:]))
        result=measure(obj/'riscv64-linux-user/qemu-riscv64',d/'count.so',elf,objdump,d)
        print(json.dumps(result,indent=2))
