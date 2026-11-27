#!/usr/bin/env python3
"""Pair one reviewed 2x2 Linux board matrix by acquisition block (not a significance test)."""
import argparse
from decimal import Decimal, localcontext
import json
from pathlib import Path
from statistics import median

NAMES=('g15-gc-lto','g15-gc-lto-ooo-strict','g15-gc-lto-ooo','g15-gc-lto-relaxed')
FACTORS=((0,1,'tune_at_strict'),(3,2,'tune_at_relaxed'),(0,3,'relax_at_default_tune'),(1,2,'relax_at_ooo_tune'))


def compare(matrix,code):
    audit={p['profile']:p for p in code['profiles']}
    order=tuple(matrix['order']); profiles=matrix['profiles']
    if (order!=tuple(NAMES[(i+j)%4] for i in range(3) for j in range(4)) or set(audit)!=set(profiles) or set(profiles)!=set(NAMES) or
            matrix['clock_mhz']!=100 or matrix['total_buffer_bytes']!=2000 or matrix['iterations_each_seed_set']!=12000):
        raise ValueError('wrong four-profile board experiment')
    cells={}
    for i,p in enumerate(NAMES):
        v=audit[p]; rows=profiles[p]['measurements']; seq=[j for j,q in enumerate(order,1) if q==p]
        if (v['elf_sha256']!=profiles[p]['elf_sha256'] or v['effective_strict_align'] is not (i in (0,1)) or
                v['explicit_mtune']!=('generic-ooo' if i in (1,2) else None) or [r['sequence'] for r in rows]!=seq):
            raise ValueError('software factor, acquisition order or ELF mismatch')
        cells[p]=rows
    def fmt(x):return format(x.quantize(Decimal('0.000001')),'f')
    out={}
    with localcontext() as ctx:
        ctx.prec=40
        for a,b,label in FACTORS:
            p,q=NAMES[a],NAMES[b]; pairs=list(zip(cells[p],cells[q])); result={}
            for seed in ('performance','validation'):
                def speed(row):
                    value=Decimal(row['runs'][seed]['iterations_per_s'])
                    if not value.is_finite() or value<=0:raise ValueError('invalid iterations/sec')
                    return value
                x=[speed(l) for l,r in pairs]; y=[speed(r) for l,r in pairs]
                changes=[(v/u-1)*100 for u,v in zip(x,y)]
                result[seed]=dict(paired_change_pct=[fmt(d) for d in changes],median_paired_change_pct=fmt(median(changes)),ratio_of_medians_change_pct=fmt((median(y)/median(x)-1)*100))
            out[label]=dict(reference=p,candidate=q,sequence_pairs=[[l['sequence'],r['sequence']] for l,r in pairs],**result)
    return dict(scope='Three interleaved blocks from one physical Rocket boot. Descriptive ratios, not confidence bounds. For each pair (candidate/reference - 1) * 100. No inference to BOOM.',contrasts=out)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('reviewed_board',type=Path);p.add_argument('reviewed_code',type=Path);a=p.parse_args()
    print(json.dumps(compare(*(json.loads(q.read_bytes()) for q in (a.reviewed_board,a.reviewed_code))),indent=2))
