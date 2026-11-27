#!/usr/bin/env python3
"""Relink a sealed BOOM model for an external-memory sensitivity experiment (no hardware)."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / 'tests'
SEEDS = ('performance', 'validation')
HEADER = 'accept_tick user opcode size source delay first_offer first_fire last_fire d_beats'


def harness(source):
    # Keep the original PC fences, UART checks and trap oracle byte-for-byte.
    edits = [('int main(int argc, char **argv) {', '#include "strict_tl_wait.hpp"\nint main(int argc, char **argv) {'),
             ('need(argc == 5,', 'need(argc == 7,'), ('TlMem ram;', 'StrictWaitRam ram(argv[5], std::stoul(argv[6]));'),
             ('ram.sample(t);', 'ram.observe(t, prv == 0, i);'), ('          t.final();', '          ram.finish(i);\n          t.final();')]
    for old, new in edits:
        if source.count(old) != 1:
            raise ValueError('expected a single harness hook: '+old)
        source = source.replace(old, new)
    return source


def link(cpp, exe, obj, include, *, env=None):
    compiler = (os.environ if env is None else env).get('CXX', 'g++')
    subprocess.run([compiler, '-std=c++17', '-O2', '-ffunction-sections', '-fdata-sections',
                    '-Wl,--gc-sections', '-I'+str(TEST), '-I'+str(obj), '-I'+str(include), '-I'+str(include/'vltstd'),
                    cpp, obj/'VChipTop__ALL.a', obj/'verilated.o', obj/'verilated_threads.o',
                    '-pthread', '-latomic', '-o', exe], check=True, env=env)


def sealed(kit, obj):
    lock = json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes())
    runpy.run_path(str(ROOT/'scripts/check-model-kit.py'))['check'](obj, kit)
    refs = lock['shared_inputs']
    design = lock['designs']['stock']
    paths = {k: TEST/k for k in refs if k.endswith(('.cpp', '.hpp'))}
    paths.update({k: obj/k for k in ('verilated.o', 'verilated_threads.o')})
    paths.update({k: (kit if k == 'CANDIDATE.sha256' else obj)/k for k in design if k != 'model'})
    fixed = {**refs, **{k: v for k, v in design.items() if k != 'model'}}
    if any(sha256(p.read_bytes()).hexdigest() != fixed[k] for k, p in paths.items()):
        raise ValueError('not the sealed stock design, objects and testbench')
    return lock, paths, fixed


def run(kit, obj, guest, out, include):
    lock, inputs, fixed = sealed(kit, obj)
    for seed in SEEDS:
        for k in ('mem.bin', 'prefix.frame'):
            inputs[seed+'/'+k] = guest/seed/'replay'/k

    def sums():
        return {k: sha256(p.read_bytes()).hexdigest() for k, p in inputs.items()}

    if sums() != fixed:
        raise ValueError('need the exact original two snapshots')
    inputs['strict_tl_wait.hpp'] = TEST/'strict_tl_wait.hpp'
    out.mkdir(mode=0o700)
    cpp = out/'replay.cpp'
    cpp.write_text(harness((TEST/'mega_user_replay.cpp').read_text()))
    inputs['replay.cpp'] = cpp
    exe = out/'model'
    before = sums()
    link(cpp, exe, obj, include)
    inputs['model'] = exe
    before['model'] = sha256(exe.read_bytes()).hexdigest()
    (out/'inputs.json').write_text(json.dumps(before, indent=2)+'\n')
    for delay in (0, 32):
        d = out/str(delay)
        d.mkdir()
        for seed in SEEDS:
            stem = guest/seed/'replay'
            n = lock['matched_windows'][seed]['user_window_instructions']
            with (d/(seed+'.uart')).open('wb') as uart, (d/(seed+'.events')).open('wb') as events:
                subprocess.run([exe, stem/'mem.bin', stem/'prefix.frame', str(n), d/(seed+'.pc'), d/(seed+'.tl'), str(delay)],
                               stdout=uart, stderr=events, check=True)
            print('completed delay', delay, seed, flush=True)
    if before != sums():
        raise ValueError('replay inputs changed during experiment')


def pin_controls(kit, obj, out, include):
    sealed(kit, obj)
    out.mkdir(mode=0o700)
    src = TEST/'strict_tl_wait_edges.cpp'
    exe = out/'fixture'
    link(src, exe, obj, include)
    for n in (0, 32):
        log = out/f'{n}.tl'
        res = subprocess.run([exe, log, str(n)], check=True, capture_output=True, text=True)
        want = [HEADER, '8 1 0 6 5 0 9 11 11 1', f'12 1 4 6 6 {n} {13+n} {14+n} {28+n} 8',
                f'{29+n} 0 4 6 7 0 {30+n} {31+n} {45+n} 8', f'END {47+n} 0 0 0']
        if log.read_text().splitlines() != want or res.stdout != f'WAIT_PIN_FIXTURE_OK delay={n}\n':
            raise ValueError('pin fixture did not see the expected transfers')
        print(res.stdout.strip(), flush=True)
    # Fault injection in a private copy only: release D.valid one tick early.
    # Compiling a sibling copy of the fixture makes its quoted include resolve here.
    text = (TEST/'strict_tl_wait.hpp').read_text()
    old = 'if (left) {\n      need(dvalid'
    if text.count(old) != 1:
        raise ValueError('missing fault injection site')
    (out/'strict_tl_wait.hpp').write_text(text.replace(old, old.replace('if (left)', 'if (left > 1)')))
    fault_src = out/src.name
    fault_src.write_bytes(src.read_bytes())
    fault = out/'fixture-fault'
    link(fault_src, fault, obj, include)
    res = subprocess.run([fault, out/'fault.tl', '32'], capture_output=True, text=True)
    if res.returncode != 1 or res.stdout or res.stderr.strip() != 'wrong A ready/D valid on fixture edge':
        raise ValueError('pin fixture failed to detect the early offer at the pins')
    print('EARLY_D_VALID_REJECTED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    for action, names in [('replay', ('kit', 'obj', 'guest', 'out', 'include')),
                          ('pins', ('kit', 'obj', 'out', 'include'))]:
        sub = subs.add_parser(action)
        for name in names:
            sub.add_argument(name, type=Path)
    args = vars(parser.parse_args())
    fn = run if args.pop('action') == 'replay' else pin_controls
    fn(**{k: p.resolve() for k, p in args.items()})
