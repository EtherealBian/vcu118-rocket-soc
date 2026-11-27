#!/usr/bin/env python3
"""Replay rounds 23993..24000 of the fixed ELF. This does not measure FPGA speed."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import runpy
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TL = runpy.run_path(str(HERE/'test-strict-tl-wait.py'))
FULL = runpy.run_path(str(HERE/'count-target-user-window.py'))
REVIEW = runpy.run_path(str(HERE/'review-strict-user-replay.py'))
SEEDS = {'performance':'0x0', 'validation':'0x3415'}
CAPTURE = ('in.json','out.json',*(f'{tag}-{area}' for tag in ('in','out') for area in ('text','rw','stack','heap')))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def harness(src):
    for old, new in [('if (pc == 0x106b0)', 'if (pc == 0x10af0 && hot == 0)'),
                     ('if (pc == 0x10af0)\n', 'if (pc == 0x10af0 && hot != 0)\n'),
                     ('epc == 0x106b0', 'epc == 0x10af0'), ('fence.size() == 5', 'fence.size() == 9')]:
        require(src.count(old) == 1, 'unexpected source hook: '+old)
        src = src.replace(old, new)
    return src


def oracle(path, seed):
    lock = json.loads((ROOT/'docs/perf-strict-target-window.json').read_bytes())['results'][seed]
    w = FULL['W']; out = (path/'guest.txt').read_text()
    crc = w['ORACLE']['crc'](out, seed, 24000)
    field = w['ORACLE']['field']; lines = out.splitlines()
    require(crc == lock['crcfinal'] and field(lines, 'Compiler version') == 'GCC15.1.0' and
            ' '.join(field(lines, 'Compiler flags').split()) == w['CM']['PROFILES'][w['PROFILE']][1], 'wrong ELF profile/CRC')
    report = (path/'counts.txt').read_text().splitlines(); rounds = []
    require(report[-1:] == ['DONE'] and len(report) > 24001, 'incomplete run')
    for i, line in enumerate(report[:24000], 1):
        m = re.fullmatch(r'R ([1-9][0-9]*) ([1-9][0-9]*)', line)
        require(m and int(m[1]) == i, 'missing round'); rounds.append(int(m[2]))
    require(sha256(struct.pack('<24000Q', *rounds)).hexdigest() == lock['ordered_round_counts_sha256'], 'full round fingerprint')
    trace = (path/'tail8.pcs').read_bytes(); n = len(trace)//4
    require(len(trace) == 4*sum(rounds[-8:]), 'incomplete tail PC order')
    return dict(by_round=rounds[-8:], dynamic_instructions=n, ordered_pc_sha256=sha256(trace).hexdigest())


def generate(q, inc, elf, out):
    require(digest(elf) == FULL['W']['ELF'] and digest(inc/'qemu-plugin.h') == FULL['HEADER'], 'wrong inputs')
    out.mkdir(mode=0o700); plugin=out/'count.so'
    subprocess.run(['cc','-std=c11','-O2','-fPIC','-Wall','-Wextra','-Werror','-fvisibility=hidden','-shared','-I'+str(inc),HERE/'strict-target-count.c','-o',plugin], check=True)
    for role, seed in SEEDS.items():
        d=out/('oracle-'+role); d.mkdir()
        with (d/'guest.txt').open('xb') as f, (d/'diag.txt').open('xb') as err:
            subprocess.run([q,'-cpu','rv64gcsu-v1.10.0','-plugin',plugin,elf,seed,seed,'0x66','24000','7','1','2000'], env=dict(os.environ,VCU_WINDOW_ROUNDS='24000',VCU_WINDOW_MODE='span',VCU_WINDOW_ORDER='tail8'), cwd=d,check=True,stdout=f,stderr=err,timeout=420)
        require(not (d/'diag.txt').stat().st_size, 'unexpected QEMU diagnostic'); oracle(d,role)


def check_fences(entry, exit_):
    for snapshot, pc, count in ((entry, 0x10af0, 23992), (exit_, 0x10f3a, 24000)):
        regs = snapshot['regs']
        require(snapshot['pc'] == pc and snapshot['priv'] == 0 and snapshot['satp'] >> 60 == 8 and
                len(regs) == 32 and regs[0] == 0 and regs[14] == count and regs[25] == 24000,
                'wrong target-tail guest fence')
    require(entry['satp'] == exit_['satp'], 'guest address space changed')


def check_guest(guest):
    text=(guest/'guest.uart').read_bytes().decode('ascii').replace('\r','')
    require('Kernel panic' not in text and text.count('\nGUEST_READY_4\n')==1 and
            '\n'+FULL['W']['ELF']+'  /bin/coremark-g15-gc-lto-ooo-strict\n' in text, 'wrong guest ELF/boot')
    expected=json.loads((ROOT/'docs/coremark-target-length-crcs.json').read_bytes())['final_crc_by_iterations']['24000']
    observed = {}
    for role,seed in SEEDS.items():
        check_fences(*(json.loads((guest/role/(tag+'.json')).read_bytes()) for tag in ('in','out')))
        begin=f'# /bin/coremark-g15-gc-lto-ooo-strict {seed} {seed} 0x66 24000 7 1 2000; echo {role}_END_$?_$((2+2))\n'
        end=f'\n{role}_END_0_4\n'
        require(text.count(begin)==text.count(end)==1 and text.index(begin)<text.index(end), 'missing exact guest run')
        report=text.split(begin)[1].split(end)[0]
        observed[role] = FULL['W']['ORACLE']['crc'](report,role,24000)
        require(observed[role] == expected[role], 'guest target CRC')
    return observed


def run(kit, obj, include, guest, reference, out):
    check_guest(guest)
    _, inputs, _ = TL['sealed'](kit,obj)
    out.mkdir(mode=0o700); cpp=out/'tail.cpp'; exe=out/'model'
    cpp.write_text(harness(inputs['mega_user_replay.cpp'].read_text())); inputs['tail.cpp']=cpp
    for role in SEEDS:
        for k in ('mem.bin','prefix.frame'):
            inputs[role+'/'+k]=guest/role/'replay'/k
        for k in ('counts.txt','guest.txt','tail8.pcs'):
            inputs[role+'/'+k]=reference/('oracle-'+role)/k
    hashes = lambda: {k:digest(p) for k,p in inputs.items()}
    inputs['guest.uart']=guest/'guest.uart'
    for role in SEEDS:
        for k in CAPTURE: inputs[role+'/'+k]=guest/role/k
    before=hashes(); TL['link'](cpp,exe,obj,include); inputs['model']=exe; before['model']=digest(exe)
    (out/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
    for role in SEEDS:
        r=oracle(reference/('oracle-'+role),role); replay=guest/role/'replay'
        with (out/(role+'.uart')).open('xb') as uart, (out/(role+'.events')).open('xb') as events:
            subprocess.run([exe,replay/'mem.bin',replay/'prefix.frame',str(r['dynamic_instructions']),out/(role+'.pc')],check=True,stdout=uart,stderr=events,timeout=900)
    require(before==hashes(), 'changed simulator inputs')


def review(guest, reference, out):
    guest_crcs = check_guest(guest)
    pins=json.loads((out/'inputs.json').read_bytes()); lock=json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes())
    for key,value in {**lock['shared_inputs'], **lock['designs']['stock']}.items():
        if '/' not in key and key!='model': require(pins.get(key)==value, 'wrong stock input: '+key)
    src=(ROOT/'tests/mega_user_replay.cpp').read_text()
    require((out/'tail.cpp').read_bytes()==harness(src).encode(), 'wrong observation hooks')
    paths={'model':out/'model', 'tail.cpp':out/'tail.cpp', 'guest.uart':guest/'guest.uart'}
    for role in SEEDS:
        for k in CAPTURE: paths[role+'/'+k]=guest/role/k
        for k in ('mem.bin','prefix.frame'): paths[role+'/'+k]=guest/role/'replay'/k
        for k in ('counts.txt','guest.txt','tail8.pcs'): paths[role+'/'+k]=reference/('oracle-'+role)/k
    for k,p in paths.items(): require(pins.get(k)==digest(p), 'changed input: '+k)
    rows={}
    for role in SEEDS:
        r=oracle(reference/('oracle-'+role),role)
        data=REVIEW['inspect']((out/(role+'.events')).read_text(),(out/(role+'.uart')).read_bytes(),(out/(role+'.pc')).read_bytes(),r,target_tail=True)
        cycles=data['by_round_cycles']
        rows[role]=dict(guest_full_run_crcfinal=guest_crcs[role], ordered_pc_sha256=data['ordered_pc_sha256'],
                        user_window_instructions=data['user_window_instructions'], user_window_cycles=data['user_window_cycles'],
                        by_round_instructions=data['by_round_instructions'], by_round_cycles=cycles,
                        first_four_cycles=sum(cycles[:4]), last_four_cycles=sum(cycles[4:]))
    return dict(scope='Stock four-wide BOOM Sv39 snapshot replay; behavioral RAM, cold microarchitecture at round 23993. Not a board score or a full-length RTL run.',elf_sha256=FULL['W']['ELF'],first_round=23993,last_round=24000,results=rows)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); subs=p.add_subparsers(dest='cmd',required=True)
    for cmd, names in [('oracle','qemu header_dir elf output'),('run','kit obj verilator_include guest reference output'),('review','guest reference output')]:
        s=subs.add_parser(cmd)
        for name in names.split(): s.add_argument(name,type=lambda x:Path(x).resolve())
    a=vars(p.parse_args()); cmd=a.pop('cmd'); paths=list(a.values())
    if cmd=='oracle': generate(*paths)
    elif cmd=='run': run(*paths)
    else: print(json.dumps(review(*paths),indent=2))
