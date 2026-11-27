#!/usr/bin/env python3
"""Compare a fresh copy/load ChipTop against two archived strict stock replays (offline)."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PAIR = runpy.run_path(str(HERE / 'review-strict-replay-pair.py'))
DERIVE = runpy.run_path(str(HERE / 'derive-copy-load-model.py'))
CHECK = runpy.run_path(str(HERE / 'check-model-kit.py'))['check']
LINK = runpy.run_path(str(HERE / 'test-strict-tl-wait.py'))['link']
SEEDS, DESIGN, RUNTIME = (PAIR[k] for k in ('SEEDS', 'DESIGN', 'RUNTIME'))
VERILATOR = '7276ac7090bc151d8366e120f108dc1b8ef4bc76bb66af051206a90fe165a462'


def doc(name):
    return json.loads((ROOT / 'docs' / name).read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def hashes(paths):
    return {k: digest(p) for k, p in paths.items()}


def write(path, value):
    with path.open('xb') as f:
        f.write((json.dumps(value, indent=2) + '\n').encode())


def read_raw(run, seed):
    return {k: (run / f'{seed}.{k}').read_bytes() for k in ('events', 'uart', 'pc')}


def translation_args(kit, obj):
    return ['--cc', '--exe', '--Mdir', str(obj), '--top-module', 'ChipTop', '-DSYNTHESIS', '-Wno-fatal',
            '-F', str(kit / 'sources.f'), str(ROOT / 'tests/rocket_chiptop.cpp'), '-CFLAGS', '-O2 -std=c++17']


def check_translation(kit, obj):
    CHECK(obj, kit)  # All ordered RTL inputs, content and translation-time stamps.
    commands = [s for s in (obj / 'VChipTop__verFiles.dat').read_text().splitlines() if s.startswith('C ')]
    if commands != ['C "' + ' '.join(translation_args(kit, obj)) + '"']:
        raise ValueError('wrong ChipTop translation flags')


def compare(seed, raw, base, ref):
    # PC and final guest state must match, regardless of instruction timing.
    res = PAIR['REPLAY']['inspect'](raw['events'].decode('ascii'), raw['uart'], raw['pc'], ref, include_widths=True)
    ev = {k: sha256(v).hexdigest() for k, v in raw.items()}
    old, orig = base['results'][seed], base['evidence'][seed]
    if any(ev[k] != orig[k] for k in ('pc', 'uart')):
        raise ValueError('PC or guest-state UART mismatch')
    for k in ('ordered_pc_sha256', 'user_window_instructions', 'by_round_instructions', 'prefix_arch_valid_pc', 'suffix_arch_valid_pc'):
        if old[k] != res[k]:
            raise ValueError('architectural observations differ: ' + k)
    a, b = old['by_round_cycles'], res['by_round_cycles']
    delta = [y - x for x, y in zip(a, b)]
    if len(a) != 4 or len(b) != 4 or sum(delta) != res['user_window_cycles'] - old['user_window_cycles']:
        raise ValueError('wrong signed cycle accounting')
    return dict(stock_cycles=a, candidate_cycles=b, candidate_minus_stock_cycles=delta,
                total_delta_cycles=sum(delta), candidate_window=res, candidate_evidence_sha256=ev)


def preflight(stock, stockobj, stockrun, candidate, guest, elf, vt):
    lock = doc('perf-strict-user-lvt.json')
    ref = doc('perf-strict-user-window.json')
    kit = doc('perf-copy-load-model.json')
    if not digest(elf) == ref['elf_sha256'] == lock['elf_sha256'] or digest(vt / 'bin/verilator_bin') != VERILATOR:
        raise ValueError('unexpected ELF or translator')
    if (digest(stock / DESIGN[0]) != kit['original_seal'] or digest(candidate / DESIGN[0]) != kit['candidate_seal'] or
            kit['original_seal'] != lock['designs']['stock'][DESIGN[0]]):
        raise ValueError('wrong pair of model inputs')
    seals, leaf = DERIVE['seals'], DERIVE['LEAF']
    DERIVE['only_one'](seals(stock), seals(candidate), kit['changed'][leaf])
    check_translation(stock, stockobj)
    if (candidate / leaf).read_bytes() != DERIVE['C']['candidate']((stock / leaf).read_bytes().decode()).encode():
        raise ValueError('independent derivation differs')
    base = PAIR['review_run']('stock', stock, stockobj, stockrun, guest, doc('perf-mega175-linux-entry.json'), ref)
    if (base['results'] != lock['matched_windows'] or base['evidence'] != lock['evidence'] or
            base['hashes'] != {**lock['shared_inputs'], **lock['designs']['stock']}):
        raise ValueError('unmatched archived stock observations')
    for seed in SEEDS:
        zero = compare(seed, read_raw(stockrun, seed), base, ref['results'][seed])
        if zero['candidate_minus_stock_cycles'] != [0] * 4 or zero['candidate_evidence_sha256'] != base['evidence'][seed]:
            raise ValueError('stock-vs-self control failed')
    return base


def shared(guest, obj):
    paths = {k: ROOT / 'tests' / k for k in PAIR['HARNESS']}
    paths.update({k: obj / k for k in RUNTIME})
    for seed in SEEDS:
        for k in ('mem.bin', 'prefix.frame'):
            paths[seed + '/' + k] = guest / seed / 'replay' / k
    return paths


def tool_env(vt):
    # Do not let the caller inject a make rule, compiler wrapper or preload into this experiment.
    return dict(HOME=os.environ['HOME'], PATH='/usr/bin:/bin', LC_ALL='C',
                VERILATOR_ROOT=str(vt / 'share/verilator'), LD_LIBRARY_PATH=str(vt / 'lib'))


def build(candidate, obj, vt, out):
    obj.mkdir()
    v = vt / 'bin/verilator_bin'
    with (out / 'build.log').open('xb') as log:
        for cmd in ([v, '--version'], [v, *translation_args(candidate, obj)],
                    ['make', '-C', obj, '-f', 'VChipTop.mk', '-j1', 'CXX=g++', 'LINK=g++', 'AR=ar', 'VChipTop__ALL.a', *RUNTIME]):
            subprocess.run(cmd, cwd=ROOT, env=tool_env(vt), stdout=log, stderr=subprocess.STDOUT, check=True)
    check_translation(candidate, obj)
    return dict(translator_sha256=digest(v), kit_sha256=digest(candidate / DESIGN[0]),
                objects=hashes({k: obj / k for k in (*DESIGN[1:], *RUNTIME)}), build_log_sha256=digest(out / 'build.log'))


def paths_for(candidate, obj, out, guest):
    return {**shared(guest, obj), DESIGN[0]: candidate / DESIGN[0], **{k: obj / k for k in DESIGN[1:]}, 'model': out / 'model'}


def check_bindings(actual, base):
    expected = base['hashes']
    # A purely combinational change need not affect the header layout. Bind its actual digest
    # in the fresh build record; only the translated archive, kit and linked model MUST differ.
    changed = {DESIGN[0], DESIGN[1], 'model'}
    if (set(actual) != set(expected) or any(actual[k] == expected[k] for k in changed) or
            any(actual[k] != expected[k] for k in expected.keys() - changed - {DESIGN[2]})):
        raise ValueError('need distinct candidate model and identical harness, runtime and snapshots')


def review(base, candidate, guest, elf, vt, out):
    obj = out / 'obj'
    check_translation(candidate, obj)
    got = hashes(paths_for(candidate, obj, out, guest))
    check_bindings(got, base)
    built = dict(translator_sha256=VERILATOR, kit_sha256=got[DESIGN[0]], objects={k: got[k] for k in (*DESIGN[1:], *RUNTIME)},
                 build_log_sha256=digest(out / 'build.log'))
    if (json.loads((out / 'inputs.json').read_bytes()) != got or json.loads((out / 'build.json').read_bytes()) != built or
            digest(vt / 'bin/verilator_bin') != VERILATOR or got[DESIGN[0]] != doc('perf-copy-load-model.json')['candidate_seal']):
        raise ValueError('unmatched build or replay inputs')
    ref = doc('perf-strict-user-window.json')
    if digest(elf) != ref['elf_sha256']:
        raise ValueError('ELF changed')
    results = {s: compare(s, read_raw(out, s), base, ref['results'][s]) for s in SEEDS}
    return dict(scope='Same strict ELF and two four-round user snapshots, stock vs. copy/load ChipTop RTL only. No FPGA timing or board score.',
                elf_sha256=ref['elf_sha256'], shared_inputs={k: got[k] for k in shared(guest, obj)},
                designs={r: {k: d[k] for k in (*DESIGN, 'model')} for r, d in [('stock', base['hashes']), ('candidate', got)]}, results=results)


def owned_output(out, candidate, inputs):
    if (out.parent != candidate.parent or out.exists() or out.is_symlink() or
            any(p == out or p in out.parents or out in p.parents for p in inputs)):
        raise ValueError('fresh disjoint sibling of private candidate kit required')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('preflight', 'run', 'review'))
    names = ('stock', 'stockobj', 'stockrun', 'candidate', 'guest', 'elf', 'verilator')
    for n in names:
        p.add_argument(n, type=Path)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    args = [getattr(a, k).resolve(strict=True) for k in names]
    stock, stockobj, stockrun, candidate, guest, elf, vt = args
    if (a.mode == 'preflight') != (a.out is None):
        p.error('preflight takes no output; run/review require --out')
    base = preflight(*args)
    if a.mode == 'preflight':
        print('VERIFIED_INPUTS_AND_STOCK_SELF_CONTROL two_seeds=2 cycle_deltas_per_seed=0,0,0,0 NOT_CANDIDATE_RESULTS')
        return
    out = a.out.absolute()
    if out.is_symlink():
        raise ValueError('output cannot be a symlink')
    out = out.resolve()
    obj = out / 'obj'
    if a.mode == 'run':
        owned_output(out, candidate, [*args, ROOT / 'scripts', ROOT / 'tests', ROOT / 'docs'])
        out.mkdir(mode=0o700)
        print('BEGIN_FRESH_SERIAL_TRANSLATION_AND_BUILD', flush=True)
        write(out / 'build.json', build(candidate, obj, vt, out))
        if hashes(shared(guest, obj)) != doc('perf-strict-user-lvt.json')['shared_inputs']:
            raise ValueError('compiled runtime or harness/guest changed')
        LINK(ROOT / 'tests/mega_user_replay.cpp', out / 'model', obj, vt / 'share/verilator/include', env=tool_env(vt))
        bindings = hashes(paths_for(candidate, obj, out, guest))
        check_bindings(bindings, base)
        write(out / 'inputs.json', bindings)
        for seed in SEEDS:
            d = guest / seed / 'replay'
            n = base['results'][seed]['user_window_instructions']
            with (out / (seed + '.events')).open('xb') as e, (out / (seed + '.uart')).open('xb') as u:
                subprocess.run([out / 'model', d / 'mem.bin', d / 'prefix.frame', str(n), out / (seed + '.pc')],
                               cwd=out, env=tool_env(vt), stdout=u, stderr=e, check=True, timeout=3600)
            print('REPLAY_EXITED ' + seed, flush=True)
    result = review(base, candidate, guest, elf, vt, out)
    if a.mode == 'review':
        if json.loads((out / 'result.json').read_bytes()) != result:
            raise ValueError('saved result did not reproduce from raw files')
        print(json.dumps(result, indent=2))
    else:
        write(out / 'result.json', result)
        print('BOTH_SNAPSHOTS_AUDITED_NOT_BOARD_PERFORMANCE')


if __name__ == '__main__':
    main()
