#!/usr/bin/env python3
"""Turn a re-reviewed same-ELF two-model comparison into cycle budgets, NOT a predicted board score."""
import argparse
import importlib.util
import json
from pathlib import Path
from statistics import median

spec=importlib.util.spec_from_file_location('cpu_compare',Path(__file__).with_name('compare-cpu-window.py')); cmp=importlib.util.module_from_spec(spec);spec.loader.exec_module(cmp)


def screen(reference, candidate, target_mhz=175, target_per_s=1000):
    if target_mhz<=0 or target_per_s<=0:raise ValueError('budget inputs must be positive')
    result=cmp.compare(reference,candidate)
    budget=target_mhz*1000000/target_per_s
    table={}
    for kind in ('performance_seed','validation_seed'):
        a,b=[side[kind]['samples'] for side in (reference,candidate)]
        if [r['sample'] for r in a]!=[0,1,2] or [r['sample'] for r in b]!=[0,1,2]:raise ValueError('need complete matched samples')
        ref=[r['cycles']/4 for r in a]; can=[r['cycles']/4 for r in b]
        if min(ref+can)<=0:raise ValueError('cycle count')
        table[kind]=dict(reference_cycles_per_iteration=ref,candidate_cycles_per_iteration=can,
            cycle_savings_median_percent=round(100*(1-median(can)/median(ref)),4),
            break_even_candidate_to_reference_clock_ratio=round(median(can)/median(ref),6),
            candidate_median_cycles_minus_budget=median(can)-budget,
            matched_windows_with_lower_cycles=sum(y<x for x,y in zip(ref,can)),
            windows_within_fixed_budget=sum(y<=budget for y in can))
    result['cycle_budget_screen']=dict(assumed_mhz=target_mhz,diagnostic_target_iterations_per_s=target_per_s,cycles_per_iteration_budget=budget,groups=table,
       limits='Four bare-metal iterations per sample; first and later windows shown separately. Clock ratio assumes these measured cycles repeat; an FPGA clock and a Linux score both require separate measurement.')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('reference_out','reference_kit','candidate_out','candidate_kit','diag'):p.add_argument(key,type=Path)
    p.add_argument('--mhz',type=int,default=175);p.add_argument('--iterations-per-second',type=int,default=1000)
    a=p.parse_args();h=Path(__file__).resolve().parents[1]/'tests/rocket_chiptop.cpp'
    result=screen(cmp.w.review(a.reference_out,a.reference_kit,a.diag,h),cmp.w.review(a.candidate_out,a.candidate_kit,a.diag,h),a.mhz,a.iterations_per_second)
    print(json.dumps(result,indent=2))
