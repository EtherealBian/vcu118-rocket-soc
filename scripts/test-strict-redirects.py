#!/usr/bin/env python3
"""Relink read-only ROB/redirect probes to the sealed four-wide model."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LIB = runpy.run_path(str(ROOT/'scripts/test-strict-tl-wait.py'))
HEADER = ROOT/'tests/strict_redirects.hpp'


def instrument(source):
    # Keep the independently checked PC and guest-state oracles intact.
    hooks = [('#define FQ(n)', '#include "strict_redirects.hpp"\n#define FQ(n)'),
             ('need(argc == 5,', 'need(argc == 6,'),
             ('bool active = false, done = false;', 'Redirects bp(argv[5]);\n    bool active = false, done = false;'),
             ('        ram.sample(t);', '        bp.before(r, ftq, i, prv == 0 && start && !stop);\n        ram.sample(t);'),
             ('                ++hot;', '                bp.commit(i, row*4+b);\n                ++hot;'),
             ('      t.clock_uncore = 1;', '      if (!t.reset_io) bp.dispatch(r,i);\n      t.clock_uncore = 1;'),
             ('          t.final();', '          bp.finish();\n          t.final();')]
    for old, new in hooks:
        if source.count(old) != 1:
            raise ValueError('missing or duplicate read-only hook: '+old)
        source = source.replace(old, new)
    return source


def run(kit, obj, guest, out, include):
    lock, inputs, fixed = LIB['sealed'](kit, obj)
    for seed in LIB['SEEDS']:
        for name in ('mem.bin', 'prefix.frame'):
            inputs[seed+'/'+name] = guest/seed/'replay'/name

    def sums():
        return {k: sha256(p.read_bytes()).hexdigest() for k, p in inputs.items()}

    if sums() != fixed:
        raise ValueError('different guest snapshots')
    out.mkdir(mode=0o700)
    cpp, exe = out/'replay.cpp', out/'model'
    cpp.write_bytes(instrument((ROOT/'tests/mega_user_replay.cpp').read_text()).encode())
    inputs.update({'replay.cpp': cpp, HEADER.name: HEADER})
    hashes = sums()
    LIB['link'](cpp, exe, obj, include)
    inputs['model'] = exe
    hashes['model'] = sha256(exe.read_bytes()).hexdigest()
    (out/'inputs.json').write_text(json.dumps(hashes, indent=2)+'\n')
    for seed in LIB['SEEDS']:
        n = lock['matched_windows'][seed]['user_window_instructions']
        d = guest/seed/'replay'
        with (out/(seed+'.uart')).open('wb') as uart, (out/(seed+'.events')).open('wb') as events:
            subprocess.run([exe, d/'mem.bin', d/'prefix.frame', str(n), out/(seed+'.pc'), out/seed],
                           stdout=uart, stderr=events, check=True)
        print(seed, 'finished', flush=True)
    if sums() != hashes:
        raise ValueError('experiment inputs changed')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('kit', 'obj', 'guest', 'out', 'include'):
        ap.add_argument(name, type=Path)
    run(**{k: v.resolve() for k, v in vars(ap.parse_args()).items()})
