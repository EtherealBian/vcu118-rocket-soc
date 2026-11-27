#!/usr/bin/env python3
"""Repeat offline verification of the physical boot and 9 fixed-iteration captures.

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


def verify_tune_machine(lines, session_pos, elf_pos, boot_nonce, n):
    if not isinstance(boot_nonce,str) or not re.fullmatch('[a-f0-9]{14}',boot_nonce):
        raise ValueError('need independently reviewed boot nonce')
    def unique(s):
        hits=[i for i,line in enumerate(lines) if line in (s,'# '+s)]
        if len(hits)!=1:raise ValueError('missing or repeated boot or machine marker')
        return hits[0]
    a=unique(f'CM_BOOT_{boot_nonce}_42_{n}'); b=unique('CM_MACHINE_END_42_'+n)
    if not session_pos<a<b<elf_pos:raise ValueError('misordered boot or machine witness')
    body=lines[a+1:b]; fields={}
    for key in ('processor','hart','uarch'):
        fields[key]=[m[1] for line in body if (m:=re.fullmatch(key+r'\s*:\s*(\S+)',line))]
    if body[:1]!=['0'] or fields!={'processor':['0'],'hart':['0'],'uarch':['sifive,rocket0']}:
        raise ValueError('expected one online Rocket CPU and hart 0')
    props={'cpus/timebase-frequency':(100000).to_bytes(4,'big'),
           'cpus/cpu@0/compatible':b'sifive,rocket0\x00riscv\x00',
           'soc/pbus_clock/clock-frequency':(100000000).to_bytes(4,'big')}
    expected=[sha256(value).hexdigest()+'  /sys/firmware/devicetree/base/'+key for key,value in props.items()]
    if [l for l in body if '/sys/firmware/devicetree/base/' in l]!=expected:
        raise ValueError('live device tree differs from reviewed Rocket clock or CPU')


def read(p): return p.read_text(encoding='utf-8-sig')

def review(boot, release, out, experiment='original', boot_nonce=None):
    cases={'original':(ORDER,'baseline',BASE_ELF), 'compilers':(COMPILER_ORDER,'o3-zb',ZB_ELF), 'portable':(PORTABLE_ORDER,'baseline',BASE_ELF), 'tune':(TUNE_ORDER,'g15-gc-lto',PORTABLE_ELFS['g15-gc-lto'])}
    if experiment not in cases:raise ValueError('unknown matrix')
    order,control,control_sha=cases[experiment]
    board=hw.lookup(boot['bit_sha256']); mhz=board['mhz']
    if board['physical_harts']!=1 or not boot['volatile_configuration'] or not boot['shell_challenge_verified'] or boot['mode']!='linux-oscheck':
        raise ValueError('expected physical single-hart Linux shell')
    tag=read(out/'session.txt').strip()
    if not re.fullmatch(r'[a-f0-9]{16}',tag):raise ValueError('bad session')
    ids={p:sha256((release/(Path(cm.binary(p)).name+'.elf')).read_bytes()).hexdigest() for p in dict.fromkeys(order)}
    if len(set(ids.values()))!=len(ids) or ids[control]!=control_sha:raise ValueError('baseline or experiment ELF identity mismatch')
    if experiment=='portable' and ids!=PORTABLE_ELFS:raise ValueError('expected the three locked portable ELFs')
    if experiment=='tune' and (boot['bit_sha256']!=BIT or ids!={TUNE[0]:PORTABLE_ELFS[TUNE[0]],TUNE[1]:PORTABLE_ELFS[TUNE[1]],TUNE[2]:TUNED_ELF}):raise ValueError('expected reviewed Rocket and three locked tuning ELFs')
    nonces=set(); digests=set(); crcs={}; runs={p:[] for p in ids}; boot_keys=['utc','mode','bit_sha256','payload_sha256','uart_sha256']
    for i,p in enumerate(order,1):
        d=out/f'{i:02}-{p}'; n=read(d/'nonce.txt').strip(); raw=(d/'uart.txt').read_bytes(); timing=json.loads(read(d/'host-ms.json'))
        checked=cm.inspect(raw,n,ids[p],12000,timing,profile=p)
        key=checked['uart_sha256']; lines=raw.decode('ascii').replace('\r','').splitlines();marker=f'CM_SESSION_{tag}_42_{n}'
        loc=[j for j,v in enumerate(lines) if v in (marker,'# '+marker)]
        def pos(v):return next(j for j,l in enumerate(lines) if l in (v,'# '+v))
        if (len(loc)!=1 or not pos('CM_LIVE_42_'+n)<loc[0]<pos(ids[p]+'  '+cm.binary(p)) or n in nonces or key in digests):raise ValueError('session, order or capture reuse')
        if experiment=='tune':verify_tune_machine(lines,loc[0],pos(ids[p]+'  '+cm.binary(p)),boot_nonce,n)
        if '-zb' in p:
            isi=pos('CM_ISA_END_42_'+n)
            ext=[m[1].split('_') for l in lines[loc[0]+1:isi] if (m:=re.fullmatch(r'isa\s*:\s*(rv64[a-z0-9_]+)',l))]
            if not loc[0]<isi<pos(ids[p]+'  '+cm.binary(p)) or len(ext)!=1 or not {'zba','zbb'}<=set(ext[0]):raise ValueError('Linux ISA not verified for Zba/Zbb')
        nonces.add(n);digests.add(key)
        saved=json.loads(read(d/'result.json'))
        if saved['iterations_requested']!=12000 or saved['boot']!={k:boot[k] for k in boot_keys} or any(saved[k]!=v for k,v in checked.items()):raise ValueError('stored record differs from verified bytes')
        finals={k:v['final_crc'] for k,v in checked['runs'].items()}
        if crcs and crcs!=finals:raise ValueError('final CRC changed at fixed iteration count')
        if experiment in ('compilers','portable','tune') and finals!={'performance':'0xd340','validation':'0xbc68'}:raise ValueError('pinned 12000-iteration final CRC mismatch')
        crcs=finals
        runs[p].append(dict(sequence=i,uart_sha256=key,runs=checked['runs']))
    def score(row,kind):return Decimal(row['runs'][kind]['iterations_per_s'])
    base=median(score(r,'performance') for r in runs[control]); stats={}
    for p,rows in runs.items():
        perf=[score(r,'performance') for r in rows]; m=median(perf)
        stats[p]=dict(compiler=cm.expected_compiler(p),flags=cm.PROFILES[p][1],elf_sha256=ids[p],performance_median=str(m),validation_median=str(median(score(r,'validation') for r in rows)),performance_min=str(min(perf)),performance_max=str(max(perf)),coremark_per_mhz=str(m/mhz),gain_vs_control_pct=str(round((m/base-1)*100,3)),all_three_at_least_1000=min(perf)>=1000,measurements=rows)
    return dict(scope='Independent physical board measurement, one hart and one context, same boot; not certified.',target_single_context_iterations_per_s=1000,clock_mhz=mhz,total_buffer_bytes=2000,iterations_each_seed_set=12000,boot={k:boot[k] for k in boot_keys},order=order,control_profile=control,profiles=stats)

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for n in ('run','capture','payload','release','out'):a.add_argument(n,type=Path)
    a.add_argument('--experiment',choices=('original','compilers','portable','tune'),default='original')
    x=a.parse_args();boot=load('verify-soc-capture').public_record(x.run,x.capture,x.payload)
    hw.verify(boot,x.run/'obj/report',json.loads(read(x.capture/'implementation.json')))
    print(json.dumps(review(boot,x.release,x.out,x.experiment,json.loads(read(x.capture/'pass.json')).get('challenge_nonce')),indent=2))
