#!/usr/bin/env python3
"""Adversarial offline checks using a real archived split-process MSHR place/route."""
import argparse
from datetime import datetime
from pathlib import Path
import runpy
from unittest.mock import patch

M=runpy.run_path(str(Path(__file__).resolve().with_name('review-mega-mshr-resume.py')))


def tests(pre,runs,case):
    rerun=lambda: M['collect'](pre,runs,[case],False)
    baseline=rerun(); original=Path.read_text; count=0
    def rejects(label,action,want):
        nonlocal count
        try:action()
        except ValueError as err:
            if want not in str(err):raise AssertionError(f'{label}: unexpected failure {err}') from err
        else:raise AssertionError(f'{label}: was accepted')
        count+=1
    def mutant(p,old,new,reason):
        def read(self,*args,**kwargs):
            data=original(self,*args,**kwargs)
            if p==self:
                assert old in data, 'control no longer applies: '+old
                return data.replace(old,new,1)
            return data
        with patch.object(Path,'read_text',read): rejects(str(p.name),rerun,reason)
    out=runs/(case+'-route'); log=runs/(case+'-route-driver')/'vivado.log'; placed=runs/(case+'-place')/'local-placed.dcp'
    rejects('swapped optimized source',lambda:M['stage'](runs,case,'place',pre/('stock' if case!='stock' else 'class_local')/'local-opt.dcp',baseline['cases'][case]['place']['source_checkpoint_sha256']), 'identity or chain')
    rejects('placed RDB as routed',lambda:M['inspect_checkpoint'](placed,['synth_design','opt_design','place_design','route_design'],datetime.min,datetime.max),'task history')
    mutant(log,'Command: route_design\n','Command: opt_design\n','unexpected tool command')
    mutant(log,'\nMSHR_RESUMED_ROUTED '+case+'\n','\n','missing/ambiguous')
    mutant(log,'Number of Partially Routed Nets     = 0\n  Number of Node Overlaps','Number of Partially Routed Nets     = 1\n  Number of Node Overlaps','incomplete final routing')
    n='path-branch-2.rpt';p=out/n
    mutant(p,'q_dc_io_lsu_brupdate_b1_mispredict_mask_reg*','q_m?_state_reg*','wrong query')
    mutant(p,', routed)',', estimated)','missing routed data path')
    old=original(pre/case/n); new=original(p)
    mutant(p,new,old,'foreign report timestamp')
    assert rerun()==baseline, 'original archive changed';print(f'{case}: {count} corrupted controls rejected; native archive still matches')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('pre','runs'):ap.add_argument(n,type=lambda s:Path(s).resolve(strict=True))
    ap.add_argument('cases',nargs='+',choices=M['M']['PREP']['CASES']);a=ap.parse_args()
    for case in a.cases:tests(a.pre,a.runs,case)
