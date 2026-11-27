#!/usr/bin/env python3
"""Recreate four sealed OOC source fixtures and check the added hardware boundary.

This checks the latency of the *measurement fixture*, not a proposal to add
pipeline stages to BOOM. No Vivado process or board connection is started.
"""
import argparse
import json
from pathlib import Path
import re
import runpy
import subprocess

HERE=Path(__file__).resolve().parent
PREP=runpy.run_path(str(HERE/'prepare-mega-regfile-ooc.py'))


def review(stock,lvt,out,iverilog,vvp,ivl):
    out.mkdir(); fixtures=out/'fixtures'; cfg=PREP['prepare'](stock,lvt,fixtures)
    cc=[iverilog]+(['-B',str(ivl)] if ivl else []); run=[vvp,'-N']+(['-M',str(ivl)] if ivl else [])
    version=subprocess.run([*cc,'-V'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True,text=True).stdout.splitlines()[0]
    tb=HERE.parent/'tests/mega_regfile_boundary_tb.v'; cases={}
    for directory,entry in cfg['cases'].items():
        d=fixtures/directory;bits=int(directory.split('-')[0]);wrap=d/'rf_boundary.v'; rows=[]
        src=[d/q for q in entry['files'] if q.endswith(('.sv','.v')) and q!=wrap.name]
        for mutate in (False,True):
            name=directory+('-wrong' if mutate else '-original');gen=wrap
            if mutate:
                needle=b'.io_read_ports_0_addr(ra_q[0 +: 7])'; b=wrap.read_bytes()
                if b.count(needle)!=1:raise ValueError('unknown read address boundary')
                gen=out/(name+'.v');gen.write_bytes(b.replace(needle,needle.replace(b'[0',b'[7')))
            exe=out/(name+'.vvp');subprocess.run([*cc,'-g2012','-DSYNTHESIS','-DRF_BITS='+str(bits),'-s','tb','-o',exe,*src,gen,tb],check=True,timeout=60)
            proc=subprocess.run([*run,exe],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
            (out/(name+'.txt')).write_bytes(proc.stdout.encode()); lines=proc.stdout.splitlines()
            if mutate:
                if proc.returncode==0 or lines!=[f'BOUNDARY_MISMATCH bits={bits} edge=130 lane=0']:raise ValueError('wrong read address not specifically detected')
            else:
                m=re.fullmatch(r'BOUNDARY_PASS bits=(\d+) edges=(\d+) lane_checks=(\d+) same_address_different_data=(\d+)\n',proc.stdout)
                if (proc.returncode!=0 or not m or list(map(int,m.groups()[:3]))!=[bits,1024,894*(12 if bits==64 else 6)] or int(m[4])<894):raise ValueError('missing readback evidence')
                rows.append(dict(edges=int(m[2]),checked_reads=int(m[3]),overlapping_new_values=int(m[4])))
        cases[directory]=dict(**rows[0],wrong_read_lane_rejected=True,fixture_sha256=entry['fixture_sha256'])
    for bits in (64,65):
        x,y=(cases[f'{bits}-{role}'] for role in ('stock','lvt'))
        if any(x[k]!=y[k] for k in x if k!='fixture_sha256') or x['fixture_sha256']==y['fixture_sha256']:raise ValueError('not matching controls')
    return dict(scope='Four-state behavioral test through the original BOOM parent inside a registered OOC measurement fixture. Legal writes only. No extra stages in the actual SoC; no vendor implementation, physical timing or CoreMark result.',
                part=cfg['part'],ooc_period_ns=cfg['period_ns'],stock_seal=cfg['stock_seal'],lvt_seal=cfg['lvt_seal'],
                bench_sha256=PREP['KIT']['h'](tb),simulator=version,cases=cases)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('stock','lvt','out'):p.add_argument(arg,type=Path)
    p.add_argument('--iverilog',default='iverilog');p.add_argument('--vvp',default='vvp');p.add_argument('--ivl',type=Path);a=p.parse_args()
    r=review(a.stock.resolve(),a.lvt.resolve(),a.out.resolve(),a.iverilog,a.vvp,a.ivl);(a.out/'result.json').write_bytes((json.dumps(r,indent=2)+'\n').encode());print('FOUR_BOUNDARY_TESTS_AND_NEGATIVE_CONTROLS_PASSED_NOT_VIVADO')
