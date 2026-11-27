#!/usr/bin/env python3
"""Replay the archived final eight Linux user rounds with the recovery ChipTop objects."""
import argparse
import json
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
T = runpy.run_path(str(HERE / 'test-strict-target-tail.py'))
L = runpy.run_path(str(HERE / 'test-mega-recovery-linux.py'))
F, need = L['F'], L['need']
h, doc = F['digest'], F['doc']
STOCK_PINS = '2f92fab6bf21fffb9ef301b78b106912b177b659e6b1d5e632066493864796a7'


def bindings(stock_board, physical, kit, previous, vt, elf, guest, oracle, stock):
    need(h(stock_board/'CANDIDATE.sha256') == L['R']['PAIR'][0], 'wrong stock physical kit')
    L['R']['I']['seals'](stock_board)
    obj = L['qualified'](physical, kit, previous, vt)
    need(h(stock/'inputs.json') == STOCK_PINS, 'wrong archived stock tail inputs')
    pins = json.loads((stock/'inputs.json').read_bytes())
    base = doc('perf-strict-target-tail.json')
    need(h(elf) == base['elf_sha256'] == T['FULL']['W']['ELF'], 'wrong benchmark ELF')
    need(T['review'](guest, oracle, stock) == base, 'stock tail control no longer reproduces')
    for k in F['PAIR']['HARNESS']:
        need(h(ROOT/'tests'/k) == pins[k], 'observer changed: '+k)
    got = {'stock_inputs_sha256':STOCK_PINS, 'recovery_inputs_sha256':h(previous/'inputs.json'),
           'verilator_sha256':h(vt/'bin/verilator_bin'), 'elf_sha256':h(elf),
           'physical_pair_sha256':[h(p/'CANDIDATE.sha256') for p in (stock_board, physical)],
           'candidate_objects':F['hashes']({k:obj/k for k in (*F['DESIGN'][1:], *F['RUNTIME'])}),
           'translation_record_sha256':h(obj/'VChipTop__verFiles.dat'), 'observer_sha256':pins['tail.cpp']}
    return obj, got, base


def inspect(out, seed, ref, base, stock):
    obs = F['read_raw'](out, seed)
    data = T['REVIEW']['inspect'](obs['events'].decode('ascii'), obs['uart'], obs['pc'], ref, target_tail=True)
    for k in ('ordered_pc_sha256','user_window_instructions','by_round_instructions'):
        need(data[k] == base[k], 'execution differs from stock: '+k)
    need(obs['uart'] == (stock/(seed+'.uart')).read_bytes(), 'different exit state witness')
    cycles = data['by_round_cycles']; delta = [n-o for n,o in zip(cycles, base['by_round_cycles'])]
    need(len(cycles) == len(delta) == 8 and sum(delta) == data['user_window_cycles']-base['user_window_cycles'], 'cycle accounting')
    return dict(user_window_instructions=data['user_window_instructions'], ordered_pc_sha256=data['ordered_pc_sha256'],
                by_round_cycles=cycles, user_window_cycles=data['user_window_cycles'], candidate_minus_stock_cycles=delta,
                guest_full_run_crcfinal=base['guest_full_run_crcfinal'], evidence_sha256=F['hashes']({k:out/(seed+'.'+k) for k in obs}))


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('mode', choices=('run','review'))
    names='stock_board physical kit previous verilator elf guest oracle stock'.split()
    for n in [*names, 'output']: p.add_argument(n,type=Path)
    a=p.parse_args(); args=[getattr(a,n).resolve(strict=True) for n in names]
    _,_,kit,_,vt,_,guest,oracle,stock=args
    need(not a.output.is_symlink(), 'symlink output'); out=a.output.resolve()
    obj, bound, base=bindings(*args); env=F['tool_env'](vt); cpp=out/'tail.cpp'; exe=out/'model'
    if a.mode=='run':
        F['owned_output'](out,kit,[*args,HERE,ROOT/'docs',ROOT/'tests']); out.mkdir(mode=0o700)
        cpp.write_bytes((stock/'tail.cpp').read_bytes()); need(h(cpp)==bound['observer_sha256'],'observer drift')
        F['LINK'](cpp,exe,obj,vt/'share/verilator/include',env=env)
        need(h(exe)!=h(stock/'model'), 'unexpected stock executable')
        F['write'](out/'bound.json',dict(bound, model_sha256=h(exe)))
        print('BOUND_RECOVERY_OBJECTS_AND_TWO_TAIL_INPUTS',flush=True)
    def check():
        need(h(cpp)==bound['observer_sha256'] and h(exe)!=h(stock/'model') and
             json.loads((out/'bound.json').read_bytes())==dict(bound,model_sha256=h(exe)), 'link/input drift')
    check(); rows={}
    for seed in T['SEEDS']:
        ref=T['oracle'](oracle/('oracle-'+seed),seed)
        if a.mode=='run':
            ram=guest/seed/'replay'
            with (out/(seed+'.uart')).open('xb') as u, (out/(seed+'.events')).open('xb') as e:
                subprocess.run([exe,ram/'mem.bin',ram/'prefix.frame',str(ref['dynamic_instructions']),out/(seed+'.pc')],
                               cwd=out,env=env,stdout=u,stderr=e,check=True,timeout=1800)
        rows[seed]=inspect(out,seed,ref,base['results'][seed],stock)
        print('VERIFIED_FINAL_EIGHT '+seed,flush=True)
    if a.mode=='run':
        need(bindings(*args)[1] == bound, 'inputs changed during replay'); check()
    result=dict(scope='Recovery ChipTop RTL from the start of round 23993. Behavioral external RAM. CRCs are from the full QEMU guest, not RTL or board scores.',
                first_round=23993,last_round=24000,**bound,model_sha256=h(exe),results=rows)
    if a.mode=='run': F['write'](out/'result.json',result)
    else: need(json.loads((out/'result.json').read_bytes())==result,'saved review differs')
    print('RECOVERY_TAIL_REVIEW_COMPLETE_NOT_BOARD_PERFORMANCE',flush=True)


if __name__=='__main__': main()
