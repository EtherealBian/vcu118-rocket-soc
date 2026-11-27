#!/usr/bin/env python3
"""Check stock and LVT runs of the same two strict guest snapshots; no hardware access."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPLAY = runpy.run_path(str(HERE / 'review-strict-user-replay.py'))
SEEDS = ('performance', 'validation')
DESIGN = ('CANDIDATE.sha256', 'VChipTop__ALL.a', 'VChipTop___024root.h')
RUNTIME = ('verilated.o', 'verilated_threads.o')
HEADERS = ('address', 'debug', 'debug_slave', 'recovery', 'sba', 'sd')
HARNESS = ('mega_user_replay.cpp', 'rocket_chiptop.cpp', *('chiptop_'+s+'.hpp' for s in HEADERS))


def digest(buf):
    return sha256(buf).hexdigest()


def manifest(file, paths):
    """Resolve full filenames, not basenames: each seed has its own mem.bin."""
    expected = {p.resolve(strict=True): key for key, p in paths.items()}
    if len(expected) != len(paths):
        raise ValueError('aliased input paths')
    seen = {}
    for line in file.read_text().splitlines():
        m = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not m:
            raise ValueError('malformed input manifest')
        p = (ROOT / m[2]).resolve(strict=True)
        key = expected.get(p)
        if key is None or key in seen or digest(p.read_bytes()) != m[1]:
            raise ValueError('unexpected, duplicate or changed replay input')
        seen[key] = m[1]
    if set(seen) != set(paths):
        raise ValueError('incomplete replay inputs')
    return seen


def review_run(role, kit, obj, run, guest, pins, oracle):
    paths = {DESIGN[0]: kit / DESIGN[0], 'model': run / 'model'}
    paths.update({name: obj / name for name in (*DESIGN[1:], *RUNTIME)})
    paths.update({name: ROOT / 'tests' / name for name in HARNESS})
    for seed in SEEDS:
        for name in ('mem.bin', 'prefix.frame'):
            paths[f'{seed}/{name}'] = guest / seed / 'replay' / name
    hashes = manifest(run / 'inputs.sha256', paths)
    if any(hashes[n] != pins['models'][role][n] for n in DESIGN):
        raise ValueError('model archive, header or kit does not match its design')
    if hashes['performance/mem.bin'] == hashes['validation/mem.bin']:
        raise ValueError('same snapshot RAM for both seeds')
    results, evidence = {}, {}
    for seed in SEEDS:
        events, uart, pc = ((run / f'{seed}.{ext}').read_bytes() for ext in ('events', 'uart', 'pc'))
        results[seed] = REPLAY['inspect'](events.decode('ascii'), uart, pc, oracle['results'][seed],
                                         include_widths=True)
        evidence[seed] = dict(pc=digest(pc), uart=digest(uart), events=digest(events))
    return dict(hashes=hashes, results=results, evidence=evidence)


def compare(stock, lvt, elf):
    bindings = (*DESIGN, 'model')
    a, b = stock['hashes'], lvt['hashes']
    if set(a) != set(b) or any((a[k] != b[k]) != (k in bindings) for k in a):
        raise ValueError('need separate designs/executables and identical stimulus/harness/runtime')
    if stock['evidence'] != lvt['evidence'] or stock['results'] != lvt['results']:
        raise ValueError('different PC, UART, events or per-round cycles; inspect both runs separately')
    return dict(scope='Stock vs LVT four-wide BOOM RTL, two four-iteration user-mode replays. '
                      'Not full Linux execution, routed timing, or FPGA throughput.',
                elf_sha256=elf, designs={r: {k: v['hashes'][k] for k in bindings}
                                        for r,v in [('stock',stock), ('lvt',lvt)]},
                shared_inputs={k:a[k] for k in sorted(a) if k not in bindings},
                evidence=stock['evidence'], matched_windows=stock['results'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for label in ('stock_kit', 'stock_obj', 'stock_run', 'lvt_kit', 'lvt_obj', 'lvt_run', 'guest'):
        p.add_argument(label, type=Path)
    args = p.parse_args()
    oracle = json.loads(REPLAY['ORACLE'].read_bytes())
    pins = json.loads((ROOT / 'docs/perf-mega175-linux-entry.json').read_bytes())
    if oracle['elf_sha256'] != pins['inputs']['coremark-g15-gc-lto-ooo-strict.elf']:
        raise ValueError('wrong ELF for this design comparison')
    runs = [review_run(r, getattr(args,r+'_kit'), getattr(args,r+'_obj'), getattr(args,r+'_run'),
                       args.guest, pins, oracle) for r in ('stock','lvt')]
    print(json.dumps(compare(*runs, oracle['elf_sha256']), indent=2))
