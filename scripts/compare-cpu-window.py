#!/usr/bin/env python3
"""Re-review both runs and compare counters, never infer a Linux score or FPGA Fmax."""
import argparse
import importlib.util
import json
from pathlib import Path

s=importlib.util.spec_from_file_location('window_model',Path(__file__).with_name('review-cpu-window.py')); w=importlib.util.module_from_spec(s);s.loader.exec_module(w)

def compare(a,b):
    for key in ('window.elf','window.bin','rocket_chiptop.cpp'):
        if a['inputs'][key] != b['inputs'][key]: raise ValueError('different workload or test harness: '+key)
    for key in ('sim','CANDIDATE.sha256'):
        if a['inputs'][key] == b['inputs'][key]:raise ValueError('reused hardware model: '+key)
    out={}
    for name in ('performance_seed','validation_seed'):
        aa,bb=a[name],b[name]
        if [r['retired'] for r in aa['samples']] != [r['retired'] for r in bb['samples']]:raise ValueError('instruction counts differ despite identical payload; investigate before attributing cycle change')
        out[name]={'reference_cycles_per_iteration':aa['median_cycles_per_iteration'],'candidate_cycles_per_iteration':bb['median_cycles_per_iteration'],
                   'retired_per_iteration':aa['median_retired_per_iteration'],'reference_ipc':aa['median_ipc'],'candidate_ipc':bb['median_ipc'],
                   'reference_to_candidate_cycle_ratio':round(aa['median_cycles_per_iteration']/bb['median_cycles_per_iteration'],6)}
    return {'scope':'Whole-core comparison of two generated ChipTop models, same preloaded executable and behavioral RAM. Different cache/predictor/issue organizations; not a board measurement or a CoreMark score.', 'reference':a,'candidate':b,'comparison':out}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('reference_out','reference_kit','candidate_out','candidate_kit','diag'):p.add_argument(arg,type=Path)
    x=p.parse_args(); h=Path(__file__).resolve().parents[1]/'tests/rocket_chiptop.cpp'
    print(json.dumps(compare(w.review(x.reference_out,x.reference_kit,x.diag,h),w.review(x.candidate_out,x.candidate_kit,x.diag,h)),indent=2))
