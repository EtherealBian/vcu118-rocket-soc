#!/usr/bin/env python3
"""Replay the sealed three-leaf physical candidate at ChipTop, not the board shell."""
import argparse
import json
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
F = runpy.run_path(str(HERE / 'test-copy-load-fullcore.py'))
P = F['PAIR']
I = runpy.run_path(str(HERE / 'verify-mega-impl-inputs.py'))
D, RT, SEEDS = F['DESIGN'], F['RUNTIME'], F['SEEDS']
h, doc = F['digest'], F['doc']
PAIR = ('b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959',
        'ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456')


def need(check, msg):
    if not check:
        raise ValueError(msg)


def physical_pair(model, stock, candidate):
    lock = doc('perf-mega175-miss-select.json')['pair_input']
    need(tuple(h(k/D[0]) for k in (stock, candidate)) == PAIR ==
         (lock['stock_sha256'], lock['candidate_sha256']), 'wrong physical pair')
    a, b, m = [I['seals'](k) for k in (stock, candidate, model)]
    seq = (model/'sources.f').read_text().splitlines()
    need(len(seq) == len(set(seq)) == lock['ordered_hdl'] == 549 and
         a['sources.f'] == b['sources.f'] == m['sources.f'] == lock['ordered_list_sha256'] and
         all({k for k in table if k.startswith('rtl/')} == set(seq) for table in (a, b, m)), 'wrong HDL/order')
    need(a.keys() == b.keys() and len(b) == lock['sealed_members'] == 589 and
         {k:b[k] for k in b if a[k] != b[k]} == lock['changed'], 'unreviewed leaf change')
    wrapper = I['TOP']
    need({k for k in seq if m[k] != a[k]} == {wrapper}, 'archived stock diverges below physical wrapper')
    for kit in (model, stock):
        text = (kit/wrapper).read_text()
        need(re.findall(r'^module\s+(\w+)', text, re.M) == ['VCU118FPGATestHarness'] and
             len(re.findall(r'^\s*ChipTop\s+chiptop0\s*\(', text, re.M)) == 1, 'wrong wrapper boundary')
    need(all(a[k] == m[k] for k in ('rom/sdboot.bin','rom/sdboot.elf')), 'different ROM')
    return dict(physical_stock_sha256=PAIR[0], candidate_sha256=PAIR[1],
                stock_model_sha256=h(model/D[0]), identical_ordered_hdl=549, changed_in_physical_pair=lock['changed'],
                only_stock_hdl_difference_outside_selected_top=wrapper)


def inputs(model, modelobj, stockrun, boardstock, candidate, guest, elf, vt):
    lock = doc('perf-strict-user-lvt.json')
    ref = doc('perf-strict-user-window.json')
    need(h(vt/'bin/verilator_bin') == F['VERILATOR'] and h(elf) == ref['elf_sha256'] == lock['elf_sha256'], 'wrong tool/ELF')
    pair = physical_pair(model, boardstock, candidate)
    F['check_translation'](model, modelobj)
    base = P['review_run']('stock', model, modelobj, stockrun, guest, doc('perf-mega175-linux-entry.json'), ref)
    need(base['results'] == lock['matched_windows'] and base['evidence'] == lock['evidence'] and
         base['hashes'] == {**lock['shared_inputs'], **lock['designs']['stock']}, 'unmatched archived control')
    return base, pair, ref


def check_window(seed, raw, base, ref):
    x = F['compare'](seed, raw, base, ref['results'][seed])
    need(x['candidate_evidence_sha256'] == base['evidence'][seed] and
         x['candidate_minus_stock_cycles'] == [0]*4 and x['candidate_window'] == base['results'][seed],
         seed + ': ordered PC, UART, event stream or timing differs')
    return dict(by_round_cycles=x['stock_cycles'], cycles=x['candidate_window']['user_window_cycles'],
                arch_instructions=x['candidate_window']['user_window_instructions'], evidence_sha256=x['candidate_evidence_sha256'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('preflight','run','review'))
    names = 'model modelobj stockrun boardstock candidate guest elf verilator'.split()
    for n in names: p.add_argument(n, type=Path)
    p.add_argument('--out', type=Path)
    a = p.parse_args(); args = [getattr(a,n).resolve(strict=True) for n in names]
    model, modelobj, stockrun, boardstock, cand, guest, elf, vt = args
    need((a.mode == 'preflight') == (a.out is None), 'run/review require --out only')
    base, pair, ref = inputs(*args)
    for seed in SEEDS:
        raw = F['read_raw'](stockrun, seed)
        check_window(seed, raw, base, ref)
        # A well-formed window still cannot hide a change to the complete event stream.
        try: check_window(seed, {**raw, 'events': raw['events'] + b'\n'}, base, ref)
        except ValueError: pass
        else: raise ValueError('changed event control not rejected')
    if a.mode == 'preflight':
        print(json.dumps(dict(scope='Inputs and stock self-controls only; candidate has not been replayed.', **pair), indent=2)); return
    need(not a.out.is_symlink(), 'output symlink')
    out = a.out.resolve(); obj = out/'obj'
    if a.mode == 'run':
        F['owned_output'](out, cand, [*args, HERE, F['ROOT']/'tests', F['ROOT']/'docs'])
        out.mkdir(mode=0o700)
        print('BEGIN_FRESH_SERIAL_BUILD', flush=True)
        F['write'](out/'build.json', F['build'](cand, obj, vt, out))
        need(F['hashes'](F['shared'](guest,obj)) == doc('perf-strict-user-lvt.json')['shared_inputs'], 'unmatched runtime')
        F['LINK'](F['ROOT']/'tests/mega_user_replay.cpp', out/'model', obj, vt/'share/verilator/include', env=F['tool_env'](vt))
        orig = F['hashes'](F['paths_for'](cand, obj, out, guest)); F['check_bindings'](orig, base)
        F['write'](out/'inputs.json', orig)
        for seed in SEEDS:
            ram = guest/seed/'replay'; count = str(base['results'][seed]['user_window_instructions'])
            with (out/(seed+'.uart')).open('xb') as u, (out/(seed+'.events')).open('xb') as e:
                subprocess.run([out/'model',ram/'mem.bin',ram/'prefix.frame',count,out/(seed+'.pc')],
                               cwd=out, env=F['tool_env'](vt), stdout=u, stderr=e, check=True, timeout=3600)
            print('REPLAY_EXITED ' + seed, flush=True)
    F['check_translation'](cand, obj)
    got = F['hashes'](F['paths_for'](cand, obj, out, guest)); F['check_bindings'](got, base)
    built = dict(translator_sha256=F['VERILATOR'], kit_sha256=PAIR[1], objects={k:got[k] for k in (*D[1:],*RT)},
                 build_log_sha256=h(out/'build.log'))
    need(json.loads((out/'inputs.json').read_bytes()) == got and json.loads((out/'build.json').read_bytes()) == built, 'build/input drift')
    result = dict(scope='ChipTop RTL, two four-round user snapshots with external behavioral RAM. Not full Linux boot, board timing or CoreMark/s.',
                  pair=pair, elf_sha256=h(elf), model_sha256=got['model'],
                  candidate_archive_sha256=got[D[1]], inputs_sha256=h(out/'inputs.json'),
                  results={s:check_window(s,F['read_raw'](out,s),base,ref) for s in SEEDS})
    if a.mode == 'run': F['write'](out/'result.json', result)
    else: need(json.loads((out/'result.json').read_bytes()) == result, 'saved review does not reproduce')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
