#!/usr/bin/env python3
"""Re-read the three-wide early-way RTL runs; require exact per-window equality, not just unchanged medians."""
import argparse
import json
from pathlib import Path
import runpy
from statistics import median

HERE = Path(__file__).resolve().parent
DOC = HERE.parent/'docs'
REVIEW = runpy.run_path(str(HERE/'compare-window-software.py'))['checked']
READ = runpy.run_path(str(HERE/'derive-mega-halt-model.py'))['read']
GROUPS = ('performance_seed','validation_seed')
TOTALS = ('model_cycles','backing_reads','backing_writes')


def summarize(pairs, originals, seals):
    if set(pairs) != {'o2','o3'} or set(originals) != set(pairs): raise ValueError('need both compiler profiles exactly once')
    out = {}; models = {}; seen = set(); matched = 0
    if len(set(seals)) != 2 or len(seals) != 2: raise ValueError('expected two distinct sealed models')
    for profile in ('o2','o3'):
        ref,new = pairs[profile]
        if ref != originals[profile]: raise ValueError('stock run differs from the published workload/control')
        a,b = ref['inputs'],new['inputs']
        if [k['CANDIDATE.sha256'] for k in (a,b)] != seals: raise ValueError('wrong model pair or direction')
        if a['sim'] == b['sim']: raise ValueError('reused simulator')
        for key in ('window.bin','window.elf','sdboot.elf','rocket_chiptop.cpp'):
            if a[key] != b[key]: raise ValueError('not the same workload, ROM or harness: '+key)
        identity = {key:(a[key],b[key]) for key in ('sim','sdboot.elf','rocket_chiptop.cpp')}
        if models and identity != models: raise ValueError('changed models, ROM or harness across profiles')
        models = identity
        for key in ('window.elf','window.bin','console_sha256'):
            value = ref[key] if key=='console_sha256' else a[key]
            if (key,value) in seen: raise ValueError('reused workload/capture: '+key)
            seen.add((key,value))
        if any(ref[k]!=new[k] for k in (*TOTALS,'console_sha256')): raise ValueError('model totals or captured UART differ')
        groups = {}
        for seed in GROUPS:
            rows = ref[seed]['samples']; other = new[seed]['samples']
            if rows != other or [r['sample'] for r in rows] != [0,1,2]: raise ValueError('different or missing sample: '+seed)
            matched += len(rows)
            groups[seed] = dict(identical_samples=rows, median_cycles_per_iteration=median(r['cycles']/4 for r in rows))
        out[profile] = dict(workload={k:a[k] for k in ('window.elf','window.bin')}, identical_console_sha256=ref['console_sha256'],
                            identical_model_totals={k:ref[k] for k in TOTALS}, **groups)
    return dict(scope='100 MHz request, three-wide BOOM, debug-preloaded bare metal and behavioral RAM. Each row is one matched stock/early-way pair, four iterations; no measured FPGA clock or Linux score.',
                kit_seals_stock_early=seals, sim_sha256_stock_early=list(models['sim']), common_rom_elf=models['sdboot.elf'][0],
                harness_sha256=models['rocket_chiptop.cpp'][0], matched_windows=matched, profiles=out)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('stock_kit','early_kit','o2_diag','o2_stock','o2_early','o3_diag','o3_stock','o3_early'):
        p.add_argument(name,type=Path)
    a = p.parse_args(); kits = (a.stock_kit,a.early_kit); pairs = {}; originals = {}
    for kit in kits: READ(kit)
    for profile in ('o2','o3'):
        pairs[profile] = [REVIEW(getattr(a,profile+'_'+side),kit,getattr(a,profile+'_diag'))
                          for side,kit in zip(('stock','early'),kits)]
        originals[profile] = json.loads((DOC/('perf-wide-'+profile+'.json')).read_bytes())['candidate']
    seals = json.loads((DOC/'perf-early-way-cone.json').read_bytes())['kit_seals']
    print(json.dumps(summarize(pairs,originals,seals),indent=2))
