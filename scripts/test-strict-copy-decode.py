#!/usr/bin/env python3
"""Relink a read-only decode-to-dispatch witness to a sealed stock BOOM (no RTL build)."""
import argparse
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CAP = runpy.run_path(str(ROOT/'scripts/test-strict-load-use.py'))
LIB = CAP['BP']['LIB']
PCS = (0x13b62, 0x13b64)


def instrument(source):
    src = CAP['BP']['instrument'](source)
    for a, b in [('#define V(n)', '#include "strict_copy_decode.hpp"\n#define V(n)'),
                 ('Redirects bp(argv[5]);', 'CopyDecode bp(argv[5]);')]:
        if src.count(a) != 1:
            raise ValueError('changed stock probe hook')
        src = src.replace(a, b)
    return src


def inputs(kit, obj, guest, previous, out):
    lock, paths, fixed = LIB['sealed'](kit, obj)
    for seed in LIB['SEEDS']:
        for k in ('mem.bin', 'prefix.frame'):
            paths[seed+'/'+k] = guest/seed/'replay'/k
    pins = lambda: {k: CAP['digest'](v) for k,v in paths.items()}
    if pins() != fixed:
        raise ValueError('wrong guest or model')
    prior = json.loads((ROOT/'docs/perf-strict-redirects.json').read_bytes())
    generated = {}
    for seed in LIB['SEEDS']:
        raw = CAP['checked_capture'](previous, seed, prior)
        generated[seed+'.select'] = CAP['selection'](raw, PCS).encode()
    generated['probe.cpp'] = instrument(paths['mega_user_replay.cpp'].read_text()).encode()
    for name in ('strict_copy_decode.hpp', 'strict_redirects.hpp'):
        generated[name] = (ROOT/'tests'/name).read_text().encode()
    paths.update({k: out/k for k in generated}); paths['model'] = out/'model'
    return lock, prior, paths, pins, generated


def run(kit, obj, guest, previous, out, inc):
    (inc / 'verilated.h').resolve(strict=True)
    lock, prior, paths, pins, generated = inputs(kit, obj, guest, previous, out)
    if any(out == p or out in p.parents or p in out.parents for p in (kit,obj,guest,previous,inc)):
        raise ValueError('independent capture directory required')
    out.mkdir(mode=0o700)
    for k, v in generated.items(): paths[k].write_bytes(v)
    LIB['link'](paths['probe.cpp'], paths['model'], obj, inc)
    before = pins(); (out/'inputs.json').write_text(json.dumps(before, indent=2)+'\n')
    for seed in LIB['SEEDS']:
        with (out/(seed+'.uart')).open('xb') as u, (out/(seed+'.events')).open('xb') as e:
            n = lock['matched_windows'][seed]['user_window_instructions']
            subprocess.run([paths['model'], paths[seed+'/mem.bin'], paths[seed+'/prefix.frame'], str(n), out/(seed+'.pc'), out/seed],
                           stdout=u, stderr=e, check=True)
        CAP['checked_capture'](out, seed, prior)
        print(seed, 'decode capture complete, stock retirement and guest state unchanged', flush=True)
    if pins() != before: raise ValueError('model, guest or probe changed')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ('kit','obj','guest','previous','out','inc'): ap.add_argument(k,type=Path)
    run(**{k:v.resolve() for k,v in vars(ap.parse_args()).items()})
