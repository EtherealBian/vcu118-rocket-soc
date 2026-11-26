#!/usr/bin/env python3
"""Check both stock POSIX CoreMark seed sets, identities and durations; no extrapolation."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


REV = '9d07b05523c16754a214a40224018a4ee908e091'
CASES = {'performance': ('0x0', '0xe9f5', '0xe714', '0x1fd7', '0x8e3a'),
         'validation': ('0x3415', '0x18f2', '0xe3c1', '0x0747', '0x8d84')}
FLAGS = '-O2 -static -s -march=rv64gc -mabi=lp64d -Wl,--build-id=none -lrt'

PROFILES = {
    'baseline': ('/bin/coremark', FLAGS),
    'o3': ('/bin/coremark-o3', FLAGS.replace('-O2 ', '-O3 ')),
    'o3-zb': ('/bin/coremark-o3-zb', FLAGS.replace('-O2 ', '-O3 ').replace('rv64gc ', 'rv64gc_zba_zbb ')),
}

def binary(profile):
    if profile not in PROFILES: raise ValueError('unknown build profile')
    return PROFILES[profile][0]

def command(nonce, iterations, profile='baseline'):
    if not re.fullmatch(r'[0-9a-f]{14}',nonce) or type(iterations) != int or not 0 <= iterations <= 1000000:
        raise ValueError('bad run parameters')
    path = binary(profile)
    cmd = [f'sha256sum {path}']
    for name,(seed,*_) in CASES.items():
        cmd += [f'echo CM_{name}_$((40+2))_{nonce}',
                f'{path} {seed} {seed} 0x66 {iterations} 7 1 2000',
                f'echo CM_{name}_RC_$?_{nonce}']
    cmd += [f'echo CM_DONE_$((40+2))_{nonce}']
    return '; '.join(cmd)

def inspect(data, nonce, elf_sha, iterations, host_ms=None, profile='baseline'):
    command(nonce,iterations,profile)
    text=data.decode('ascii').replace('\r\n','\n'); rows=text.splitlines()
    if not re.fullmatch('[0-9a-f]{64}',elf_sha) or any(s in text for s in ('Kernel panic','Errors detected','ERROR!','Cannot validate operation')):
        raise ValueError('invalid ELF identity or failed guest')
    def pos(row):
        hits=[i for i,v in enumerate(rows) if v in (row,'# '+row)]
        if len(hits)!=1:raise ValueError('missing or ambiguous '+row)
        return hits[0]
    prev=pos(f'CM_LIVE_42_{nonce}'); identity=pos(elf_sha+'  '+binary(profile))
    if prev>=identity:raise ValueError('ELF not checked in this boot')
    prev=identity; result={}
    for name,(_,seed,lst,mat,state) in CASES.items():
        start=pos(f'CM_{name}_42_{nonce}');end=pos(f'CM_{name}_RC_0_{nonce}')
        if not prev<start<end:raise ValueError('bad run order or exit status')
        prev=end;lines=rows[start+1:end]
        def field(k):
            hits=[m[1].strip() for line in lines if (m:=re.fullmatch(re.escape(k)+r'\s*:\s*(.+)',line))]
            if len(hits)!=1:raise ValueError('invalid field '+k)
            return hits[0]
        def once(s):
            if lines.count(s)!=1:raise ValueError('missing or repeated '+s)
        once('2K '+name+' run parameters for coremark.');once('Correct operation validated. See README.md for run and reporting rules.')
        if ([field(k) for k in ('seedcrc','[0]crclist','[0]crcmatrix','[0]crcstate')] != [seed,lst,mat,state] or field('CoreMark Size')!='666' or any(line.startswith('Parallel ') for line in lines)):
            raise ValueError('wrong CRC, data size or context count')
        flags=' '.join(field('Compiler flags').split());compiler=field('Compiler version');ticks=int(field('Total ticks'));secs=Decimal(field('Total time (secs)'));rate=Decimal(field('Iterations/Sec'));n=int(field('Iterations'));final=field('[0]crcfinal')
        if (compiler!='GCC13.3.0' or flags!=PROFILES[profile][1] or not re.fullmatch('0x[0-9a-f]{4}',final) or not secs.is_finite() or not rate.is_finite() or secs<10 or ticks!=secs*1000 or n<=0 or (iterations and n!=iterations) or abs(rate - n/secs)>Decimal('.000002')):raise ValueError('invalid build, duration or rate')
        score=[x for x in lines if x.startswith('CoreMark 1.0 : ')]
        if name=='performance':
            if len(score)!=1:raise ValueError('missing or repeated performance summary')
            summary=re.fullmatch(r'CoreMark 1\.0 : ([0-9]+(?:\.[0-9]+)?) / ([^/]+) / Heap',' '.join(score[0].split()))
            if not summary or Decimal(summary[1])!=rate or summary[2]!=compiler+' '+flags:raise ValueError('inconsistent performance summary')
        elif score:raise ValueError('unexpected performance summary in validation mode')
        result[name]=dict(iterations=n,elapsed_s=str(secs),iterations_per_s=str(rate),seedcrc=seed,list_crc=lst,matrix_crc=mat,state_crc=state,final_crc=final)
        if host_ms is not None:
            ms=host_ms[name]
            if not iterations or type(ms)!=int or abs(ms-ticks)>max(2000,ticks//20):raise ValueError('host time does not agree with fixed-iteration guest interval')
            result[name]['host_observed_ms']=ms
    if pos('CM_DONE_42_'+nonce)<=prev:raise ValueError('missing final handoff')
    return dict(profile=profile,upstream=REV,elf_sha256=elf_sha,compiler=compiler,flags=flags,context_count=1,total_buffer_bytes=2000,allocation='heap',runs=result,uart_sha256=hashlib.sha256(data).hexdigest())

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--command',action='store_true');p.add_argument('nonce');p.add_argument('iterations',type=int);p.add_argument('uart',nargs='?',type=Path);p.add_argument('elf',nargs='?',type=Path);p.add_argument('--host-ms',type=Path);p.add_argument('--profile',choices=tuple(PROFILES),default='baseline');a=p.parse_args()
    if a.command:print(command(a.nonce,a.iterations,a.profile))
    else:print(json.dumps(inspect(a.uart.read_bytes(),a.nonce,hashlib.sha256(a.elf.read_bytes()).hexdigest(),a.iterations,json.loads(a.host_ms.read_text()) if a.host_ms else None,a.profile),indent=2))
