#!/usr/bin/env python3
"""Compare the 175 MHz three-wide ROM pin regressions, re-reading both raw runs."""
import argparse
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
MODEL = HERE.parent / 'docs' / 'perf175-early-way-model.json'
review = runpy.run_path(str(HERE / 'review-clocked-rom-link.py'))['review']
DISTINCT = ('CANDIDATE.sha256', 'model', 'VChipTop__ALL.a')


def compare(stock, early, seals):
    """Both arguments must be complete outputs of review(..., 175, 'single')."""
    a, b = stock['inputs'], early['inputs']
    if (a[DISTINCT[0]], b[DISTINCT[0]]) != tuple(seals):
        raise ValueError('not the specified stock and derived models in that order')
    if a.keys() != b.keys() or {k for k in a if a[k] != b[k]} != set(DISTINCT):
        raise ValueError('reused model or mismatching ROM, testbench or workload')
    if stock.keys() != early.keys() or any(stock[k] != early[k] for k in stock if k != 'inputs'):
        raise ValueError('pin observations differ')
    return {
        'scope': 'Matched stock and early-way three-wide ChipTop ROM pin simulations at the 175 MHz design divider. No board, physical DDR, routed clock, or Linux benchmark.',
        'order': ['stock175', 'early_way175'],
        'distinct_inputs': {k: [a[k], b[k]] for k in DISTINCT},
        'identical_inputs': {k: v for k, v in a.items() if k not in DISTINCT},
        'identical_observations': {k: v for k, v in stock.items() if k not in ('scope', 'inputs')},
    }


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('stock_out', 'stock_kit', 'early_out', 'early_kit'):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    identity = json.loads(MODEL.read_bytes())
    seals = (identity['stock100_donor100_stock175_seals'][2], identity['derived175_seal'])
    print(json.dumps(compare(review(args.stock_out, args.stock_kit, 175, 'single'),
                             review(args.early_out, args.early_kit, 175, 'single'), seals), indent=2))
