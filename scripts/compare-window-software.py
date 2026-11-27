#!/usr/bin/env python3
"""Compare two software payloads on one unchanged RTL model. Never estimates a board score."""
import argparse
import importlib.util
import json
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('window_review', HERE/'review-cpu-window.py')
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)


def compare(a, b):
    for key in ('sim', 'CANDIDATE.sha256', 'rocket_chiptop.cpp', 'sdboot.elf'):
        if a['inputs'][key] != b['inputs'][key]:
            raise ValueError('different hardware or harness: ' + key)
    for key in ('window.elf', 'window.bin'):
        if a['inputs'][key] == b['inputs'][key]:
            raise ValueError('expected genuinely different software: ' + key)
    rows = {}
    for name in ('performance_seed', 'validation_seed'):
        ref, candidate = a[name]['samples'], b[name]['samples']
        for samples in (ref, candidate):
            if [r['sample'] for r in samples] != [0, 1, 2] or any(min(r['cycles'],r['retired']) <= 0 for r in samples):
                raise ValueError('incomplete matched set')
        ca, cb = [[r['cycles'] / 4 for r in group] for group in (ref, candidate)]
        ra, rb = [median(r['retired']/4 for r in group) for group in (ref, candidate)]
        rows[name] = dict(reference_cycles_per_iteration=ca, candidate_cycles_per_iteration=cb,
                          reference_median=median(ca), candidate_median=median(cb),
                          median_cycle_change_pct=round(100*(median(cb)/median(ca)-1),4),
                          median_retired_change_pct=round(100*(rb/ra-1),4),
                          candidate_lower_cycles_count=sum(y<x for x,y in zip(ca,cb)))
    return dict(scope='Same functional hardware model, debug-preloaded different software. Four iterations per sample; not a Linux or physical score.',
                reference=a, candidate=b, comparison=rows)


def checked(out, kit, diag):
    result=window.review(out, kit, diag, HERE.parent/'tests/rocket_chiptop.cpp')
    if result != json.loads((out/'result.json').read_bytes()):
        raise ValueError('stored result differs from independent review')
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('kit','reference_out','reference_diag','candidate_out','candidate_diag'):
        p.add_argument(arg, type=Path)
    x=p.parse_args()
    print(json.dumps(compare(checked(x.reference_out,x.kit,x.reference_diag),checked(x.candidate_out,x.kit,x.candidate_diag)),indent=2))
