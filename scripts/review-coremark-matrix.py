#!/usr/bin/env python3
"""Repeat offline verification of the physical boot and a fixed-iteration capture matrix.

The CLI binds the capture to allowlisted bit and routed clock/timing reports.
"""
import argparse
from decimal import Decimal
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
from statistics import median


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


cm=load('review-coremark')
hw=load('benchmark_hardware')
BIT=hw.ROCKET_BIT
BASE_ELF='beafaa8dbebe44215cbc142639c4dd5d46eb0feaf9f14356078d035742cad3ec'
ORDER=('baseline','o3','o3-zb','o3','o3-zb','baseline','o3-zb','baseline','o3')

COMPILERS=('o3-zb','g15-zb-lto','o3-zb-lto-unroll')
COMPILER_ORDER=tuple(COMPILERS[(row+col)%3] for row in range(3) for col in range(3))
ZB_ELF='327d504dab206371a52e3483c487da75cffb355aa8bcd247d33de75c1c484882'

PORTABLE=('baseline','o3','g15-gc-lto')
PORTABLE_ORDER=tuple(PORTABLE[(row+col)%3] for row in range(3) for col in range(3))
PORTABLE_ELFS={
    'baseline':BASE_ELF,
    'o3':'45ff8489abbae8c54d13c7155e4c0397c981b34fffb351c9cc1344e694b72113',
    'g15-gc-lto':'0ab2e1c3baf03a98c23383268e1f792c9d955e6fe54b15c0e536ac21f22a4232',
}

TUNE=('baseline','g15-gc-lto','g15-gc-lto-ooo')
TUNE_ORDER=tuple(TUNE[(row+col)%3] for row in range(3) for col in range(3))
TUNED_ELF='54144e7c53a35078afe3f075469e68e87ea9b5de6837530f4be76c67725ecce9'


# Four toolchain configurations, three blocks; each profile occurs once per
# block and visits three distinct within-block positions (not a full 4x4).
ALIGN=('g15-gc-lto','g15-gc-lto-ooo-strict','g15-gc-lto-ooo','g15-gc-lto-relaxed')
ALIGN_ORDER=tuple(ALIGN[(i+j)%4] for i in range(3) for j in range(4))
ALIGN_ELFS=dict(zip(ALIGN,(PORTABLE_ELFS['g15-gc-lto'],
    '61f7c4579b762f86d7d7dc93d4c385d08e50248f3dd6a8a9105fd5e88b58886a',TUNED_ELF,
    '35419f1ea8ece2ceed2c0831d00c562752d52c1602e97d94e35667e1ac81112c')))

# Score attempt: three pairs using the same portable, explicitly aligned ELF.
TARGET_PROFILE='g15-gc-lto-ooo-strict'
TARGET_SHA=ALIGN_ELFS[TARGET_PROFILE]
TARGET_PAYLOAD='b952fffeca0afa1cde8578f9a39677ebb36bdbccce35ba61dcaa6b5d0b16aeac'
witness=load('linux_machine_witness')


def read(p): return p.read_text(encoding='utf-8-sig')

LENGTH_CRCS={12000:{'performance':'0xd340','validation':'0xbc68'},
             24000:{'performance':'0x4983','validation':'0xeb93'}}

def check_length(experiment,iterations):
    if type(iterations)!=int or iterations not in LENGTH_CRCS or (experiment!='target' and iterations!=12000):
        raise ValueError('unreviewed matrix length or length outside target experiment')

def target_release(boot):
    # public_record() already rehashes the frame and the supplied stage file.
    # A release with the same ELF but a different kernel or initramfs is not
    # the matched Rocket/BOOM trial. Do not use the historical Rocket *bit* here.
    if boot['payload_sha256'] != TARGET_PAYLOAD:
        raise ValueError('target requires the locked packed Linux payload')


def target_invocation(lines, machine_end, elf_line, nonce, iterations):
    # "CoreMark Size : 666" is per algorithm (integer division); by itself it
    # cannot distinguish total sizes 1998, 1999 and 2000. Check the actual ash
    # echo between the live-machine result and the SHA output. Construct the
    # target contract independently of cm.command(), which drives the board.
    exe = '/bin/coremark-g15-gc-lto-ooo-strict'
    args = f'0x66 {iterations} 7 1 2000'
    commands = [f'sha256sum {exe}']
    for mode, seed in (('performance', '0x0'), ('validation', '0x3415')):
        commands.extend((f'echo CM_{mode}_$((40+2))_{nonce}',
                         f'{exe} {seed} {seed} {args}',
                         f'echo CM_{mode}_RC_$?_{nonce}'))
    commands.append(f'echo CM_DONE_$((40+2))_{nonce}')
    echo = '; '.join(commands)
    echoes = [i for i, row in enumerate(lines) if row in (echo, '# '+echo)]
    if echoes != [machine_end + 1] or elf_line != machine_end + 2:
        raise ValueError('missing, repeated or different target invocation before the ELF digest')


def review(boot, release, out, experiment='original', boot_nonce=None, iterations=12000):
    check_length(experiment,iterations)
    cases={'original':(ORDER,'baseline',BASE_ELF), 'compilers':(COMPILER_ORDER,'o3-zb',ZB_ELF), 'portable':(PORTABLE_ORDER,'baseline',BASE_ELF), 'tune':(TUNE_ORDER,'g15-gc-lto',PORTABLE_ELFS['g15-gc-lto'])}
    cases['align']=(ALIGN_ORDER,ALIGN[0],ALIGN_ELFS[ALIGN[0]])
    cases['target']=((TARGET_PROFILE,)*3,TARGET_PROFILE,TARGET_SHA)
    if experiment not in cases:raise ValueError('unknown matrix')
    order,control,control_sha=cases[experiment]
    board=hw.lookup(boot['bit_sha256']); mhz=board['mhz']
    if experiment=='target':target_release(boot)
    if board['physical_harts']!=1 or not boot['volatile_configuration'] or not boot['shell_challenge_verified'] or boot['mode']!='linux-oscheck':
        raise ValueError('expected physical single-hart Linux shell')
    tag=read(out/'session.txt').strip()
    if not re.fullmatch(r'[a-f0-9]{16}',tag):raise ValueError('bad session')
    ids={p:sha256((release/(Path(cm.binary(p)).name+'.elf')).read_bytes()).hexdigest() for p in dict.fromkeys(order)}
    if len(set(ids.values()))!=len(ids) or ids[control]!=control_sha:raise ValueError('baseline or experiment ELF identity mismatch')
    if experiment=='portable' and ids!=PORTABLE_ELFS:raise ValueError('expected the three locked portable ELFs')
    if experiment=='tune' and (boot['bit_sha256']!=BIT or ids!={TUNE[0]:PORTABLE_ELFS[TUNE[0]],TUNE[1]:PORTABLE_ELFS[TUNE[1]],TUNE[2]:TUNED_ELF}):raise ValueError('expected reviewed Rocket and three locked tuning ELFs')
    if experiment=='align' and (boot['bit_sha256']!=BIT or ids!=ALIGN_ELFS):raise ValueError('expected reviewed Rocket and four alignment ELFs')
    nonces=set(); digests=set(); crcs={}; runs={p:[] for p in ids}; boot_keys=['utc','mode','bit_sha256','payload_sha256','uart_sha256']
    for i,p in enumerate(order,1):
        d=out/f'{i:02}-{p}'; n=read(d/'nonce.txt').strip(); raw=(d/'uart.txt').read_bytes(); timing=json.loads(read(d/'host-ms.json'))
        if not isinstance(timing,dict) or set(timing)!={'performance','validation'} or any(type(ms)!=int or ms<=0 for ms in timing.values()):
            raise ValueError('physical matrix needs a positive host time for each seed')
        checked=cm.inspect(raw,n,ids[p],iterations,timing,profile=p)
        key=checked['uart_sha256']; text=raw.decode('ascii'); marker=f'CM_SESSION_{tag}_42_{n}'
        lines=(text.replace('\r\n','\n').split('\n') if experiment=='target' else text.replace('\r','').splitlines())
        loc=[j for j,v in enumerate(lines) if v in (marker,'# '+marker)]
        def pos(v):return next(j for j,l in enumerate(lines) if l in (v,'# '+v))
        if (len(loc)!=1 or not pos('CM_LIVE_42_'+n)<loc[0]<pos(ids[p]+'  '+cm.binary(p)) or n in nonces or key in digests):raise ValueError('session, order or capture reuse')
        if experiment in ('tune','align','target'):
            elf_line=pos(ids[p]+'  '+cm.binary(p))
            witness.inspect(lines,loc[0],elf_line,boot_nonce,n,board['runtime_contract'])
            if experiment=='target':target_invocation(lines,pos('CM_MACHINE_END_42_'+n),elf_line,n,iterations)
        if '-zb' in p:
            isi=pos('CM_ISA_END_42_'+n)
            ext=[m[1].split('_') for l in lines[loc[0]+1:isi] if (m:=re.fullmatch(r'isa\s*:\s*(rv64[a-z0-9_]+)',l))]
            if not loc[0]<isi<pos(ids[p]+'  '+cm.binary(p)) or len(ext)!=1 or not {'zba','zbb'}<=set(ext[0]):raise ValueError('Linux ISA not verified for Zba/Zbb')
        nonces.add(n);digests.add(key)
        saved=json.loads(read(d/'result.json'))
        if saved['iterations_requested']!=iterations or saved['boot']!={k:boot[k] for k in boot_keys} or any(saved[k]!=v for k,v in checked.items()):raise ValueError('stored record differs from verified bytes')
        finals={k:v['final_crc'] for k,v in checked['runs'].items()}
        if crcs and crcs!=finals:raise ValueError('final CRC changed at fixed iteration count')
        if experiment in ('compilers','portable','tune','align','target') and finals!=LENGTH_CRCS[iterations]:raise ValueError(f'pinned {iterations}-iteration final CRC mismatch')
        crcs=finals
        runs[p].append(dict(sequence=i,uart_sha256=key,runs=checked['runs']))
    def score(row,kind):return Decimal(row['runs'][kind]['iterations_per_s'])
    base=median(score(r,'performance') for r in runs[control]); stats={}
    for p,rows in runs.items():
        perf=[score(r,'performance') for r in rows]; m=median(perf)
        stats[p]=dict(compiler=cm.expected_compiler(p),flags=cm.PROFILES[p][1],elf_sha256=ids[p],performance_median=str(m),validation_median=str(median(score(r,'validation') for r in rows)),performance_min=str(min(perf)),performance_max=str(max(perf)),coremark_per_mhz=str(m/mhz),gain_vs_control_pct=str(round((m/base-1)*100,3)),all_three_at_least_1000=min(perf)>=1000,measurements=rows)
    return dict(scope='Independent physical board measurement, one hart and one context, same boot; not certified.',target_single_context_iterations_per_s=1000,clock_mhz=mhz,total_buffer_bytes=2000,iterations_each_seed_set=iterations,boot={k:boot[k] for k in boot_keys},order=order,control_profile=control,profiles=stats)

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for n in ('run','capture','payload','release','out'):a.add_argument(n,type=Path)
    a.add_argument('--experiment',choices=('original','compilers','portable','tune','align','target'),default='original')
    a.add_argument('--iterations',choices=tuple(LENGTH_CRCS),type=int,default=12000,help='fixed count for every seed in the matrix; long runs only for target')
    a.add_argument('--preflight',action='store_true',help='target only: verify programmed boot and selected ELF without reviewing timings')
    x=a.parse_args();check_length(x.experiment,x.iterations);boot=load('verify-soc-capture').public_record(x.run,x.capture,x.payload)
    hw.verify(boot,x.run/'obj/report',json.loads(read(x.capture/'implementation.json')))
    if x.preflight:
        if (x.experiment!='target' or boot['mode']!='linux-oscheck' or not boot['volatile_configuration'] or
                not boot['shell_challenge_verified'] or hw.lookup(boot['bit_sha256'])['physical_harts']!=1 or
                sha256((x.release/('coremark-'+TARGET_PROFILE+'.elf')).read_bytes()).hexdigest()!=TARGET_SHA):
            raise ValueError('target preflight requires reviewed boot and locked portable ELF')
        target_release(boot)
        witness.expected(hw.lookup(boot['bit_sha256'])['runtime_contract'])
        print('REGISTERED_TARGET_AND_ELF_PRECHECKED_NOT_A_SCORE');raise SystemExit(0)
    print(json.dumps(review(boot,x.release,x.out,x.experiment,json.loads(read(x.capture/'pass.json')).get('challenge_nonce'),x.iterations),indent=2))
