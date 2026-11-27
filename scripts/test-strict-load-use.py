#!/usr/bin/env python3
"""Observe true load result values, ALU branch inputs and B1 without altering the guest or RTL."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BP = runpy.run_path(str(HERE/'test-strict-redirects.py'))
SHELL = runpy.run_path(str(HERE/'test-mega-linux-shell.py'))
PCS = (0x13ea4, 0x13eac, 0x13eda)


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def checked_capture(base, seed, oracle):
    raw = {k:(base/(seed+'.'+k)).read_bytes() for k in ('pc','tickets','redirects','events','uart')}
    if {k:sha256(v).hexdigest() for k,v in raw.items()} != oracle['results'][seed]['sha256']:
        raise ValueError('different retirement, redirect or guest trace')
    return raw


def selection(raw, pcs_of_interest=PCS):
    pcs, tickets = raw['pc'], raw['tickets']
    if len(pcs)%4 or len(tickets)!=len(pcs)*2:
        raise ValueError('malformed paired trace')
    return ''.join(f'{t} {pc}\n' for (pc,), (_,t) in zip(struct.iter_unpack('<I',pcs),struct.iter_unpack('<II',tickets)) if pc in pcs_of_interest)


def instrument(base_source, address_chain=False, left_load=False):
    src=BP['instrument'](base_source)
    for old,new in [('#include "strict_redirects.hpp"','#include "strict_redirects.hpp"\n#include "strict_load_use.hpp"'),('Redirects bp(argv[5]);','LoadUse bp(argv[5]);')]:
        if src.count(old)!=1: raise ValueError('changed probe hook')
        src=src.replace(old,new)
    if address_chain:
        src=src.replace('#include "strict_load_use.hpp"', '#include "strict_load_use.hpp"\n#include "strict_address_chain.hpp"').replace('LoadUse bp(argv[5]);', 'AddressChain bp(argv[5]);')
    if left_load:
        if not address_chain: raise ValueError("left-load probe requires address-chain baseline")
        src=src.replace('#include "strict_address_chain.hpp"', '#include "strict_address_chain.hpp"\n#include "strict_left_load.hpp"').replace('AddressChain bp(argv[5]);', 'LeftLoad bp(argv[5]);')
    return src


def run(kit,obj,guest,baseline,out,include,address_chain=False, left_load=False):
    lock=json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes())
    oracle=json.loads((ROOT/'docs/perf-strict-redirects.json').read_bytes())
    runpy.run_path(str(HERE/'check-model-kit.py'))['check'](obj,kit)
    subprocess.run(['sha256sum','--quiet','-c','CANDIDATE.sha256'],cwd=kit,check=True)
    out.mkdir(mode=0o700)
    fixed = {**lock['shared_inputs'], **{k:v for k,v in lock['designs']['stock'].items() if k!='model'}}
    inputs = {}
    for k,h in fixed.items():
        if k.endswith(('.cpp','.hpp')):
            src=ROOT/'tests'/k; p=out/k; p.write_bytes(SHELL['pinned_source'](k,src.read_bytes(),h))
        elif '/' in k:
            s,name=k.split('/'); p=guest/s/'replay'/name
        else:
            p=(kit if k=='CANDIDATE.sha256' else obj)/k
        if digest(p)!=h: raise ValueError('changed sealed input: '+k)
        inputs[k]=p
    for name in ['strict_redirects.hpp','strict_load_use.hpp'] + (['strict_address_chain.hpp'] if address_chain else []) + (['strict_left_load.hpp'] if left_load else []):
        p=out/name; p.write_bytes((ROOT/'tests'/name).read_text().encode()); inputs[name]=p
    cpp=out/'probe.cpp'; exe=out/'model'
    src=instrument(inputs['mega_user_replay.cpp'].read_text(),address_chain,left_load)
    cpp.write_bytes(src.encode()); inputs[cpp.name]=cpp
    for seed in BP['LIB']['SEEDS']:
        p=out/(seed+'.select'); p.write_bytes(selection(checked_capture(baseline,seed,oracle), PCS + ((0x13ea2,) if address_chain else ()) + ((0x13e9e,) if left_load else ())).encode()); inputs[p.name]=p
    hashes={k:digest(p) for k,p in inputs.items()}
    BP['LIB']['link'](cpp,exe,obj,include)
    inputs['model']=exe; hashes['model']=digest(exe)
    (out/'inputs.json').write_text(json.dumps(hashes,indent=2)+'\n')
    for seed in BP['LIB']['SEEDS']:
        with (out/(seed+'.uart')).open('wb') as uart,(out/(seed+'.events')).open('wb') as events:
            subprocess.run([exe,inputs[seed+'/mem.bin'],inputs[seed+'/prefix.frame'],str(lock['matched_windows'][seed]['user_window_instructions']),out/(seed+'.pc'),out/seed], check=True,stdout=uart,stderr=events)
        checked_capture(out,seed,oracle)
        print(seed,'reference traces unchanged',flush=True)
    if {k:digest(p) for k,p in inputs.items()}!=hashes: raise ValueError('inputs changed during capture')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('kit','obj','guest','baseline','out','include'): ap.add_argument(name,type=Path)
    ap.add_argument('--address-chain',action='store_true',help='also capture the x10 pointer-to-halfword address chain')
    ap.add_argument('--left-load',action='store_true',help='also trace x6 and its fall-through pointer through the cache port')
    a=ap.parse_args(); run(*(getattr(a,k).resolve() for k in ('kit','obj','guest','baseline','out','include')), address_chain=a.address_chain or a.left_load,left_load=a.left_load)
