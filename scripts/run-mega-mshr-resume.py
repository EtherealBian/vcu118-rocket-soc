#!/usr/bin/env python3
"""Resume one verified OOC stage without pre-empting the whole-SoC Vivado run (Windows)."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import runpy
import subprocess
import time

HERE = Path(__file__).resolve().parent
R = runpy.run_path(str(HERE/'review-mega-mshr-resume.py'))
need, h = R['need'], R['h']
MiB=1024**2


class MemoryStatus(ctypes.Structure):
    _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(n,ctypes.c_uint64) for n in ('total','available','total_commit','available_commit','virtual','available_virtual','unused')]


def memory():
    info=MemoryStatus(); info.length=ctypes.sizeof(info)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)): raise ctypes.WinError()
    return info.available//MiB, info.available_commit//MiB


def run(vivado, pre, runs, primary, case, verb):
    need(os.name=='nt' and vivado.name.lower()=='vivado.bat','need Windows Vivado launcher')
    src=pre/case/'local-opt.dcp'; expected=json.loads(R['REF'].read_bytes())['cases'][case]['checkpoint_sha256']
    if verb=='route':
        verified,src,_=R['stage'](runs,case,'place',src,expected); expected=verified['checkpoint_sha256']
    driver=R['DRIVER']; fingerprint=h(driver); need(h(src)==expected, 'wrong source for this case and stage')
    out=runs/(case+'-'+verb); working=runs/(out.name+'-driver')
    need(not out.exists() and not working.exists(), 'refusing to reuse a stage directory')
    physical,commit=memory(); need(physical>=6700 and commit>=14000 and not primary.exists(),'primary implementation has priority; not launching')
    working.mkdir(parents=True); noun={'place':'placed','route':'routed'}[verb]; dst=out/('local-'+noun+'.dcp')
    args=[str(vivado),'-mode','batch','-log','vivado.log','-nojournal','-source',driver.as_posix(),'-tclargs',verb,case,src.as_posix(),out.as_posix()]
    low=physical; guard=None
    with (working/'console.txt').open('xb') as console:
        proc=subprocess.Popen(args,cwd=working,stdout=console,stderr=subprocess.STDOUT,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS|subprocess.CREATE_NO_WINDOW)
        try:
            while proc.poll() is None:
                physical,commit=memory();low=min(low,physical)
                if physical<3150 or commit<9000 or primary.exists():
                    guard='yield: main synthesis exit, memory or commit reserve';break
                time.sleep(.5)
        finally:
            if proc.poll() is None:
                # Kill only the child tree this process launched, never an unrelated Vivado.
                subprocess.run(['taskkill','/pid',str(proc.pid),'/t','/f'],check=False);proc.wait()
    marker='MSHR_RESUMED_'+noun.upper()+' '+case
    complete=(guard is None and proc.returncode==0 and dst.is_file() and h(driver)==fingerprint and h(src)==expected and marker in (working/'console.txt').read_text(errors='replace').splitlines())
    record=dict(case=case,stage=verb,rc=proc.returncode,guard=guard,low_available_MiB=low,source_checkpoint_sha256=expected,driver_sha256=fingerprint,complete=complete)
    if complete:record['output_checkpoint_sha256']=h(dst)
    (working/'exit.json').write_text(json.dumps(record)+'\n');need(complete,'stage incomplete; see its exit record')
    print('MSHR_CHECKPOINT_READY',case,verb)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('vivado','pre','runs','primary_checkpoint'):ap.add_argument(n,type=lambda s:Path(s).resolve())
    ap.add_argument('case',choices=R['M']['PREP']['CASES']);ap.add_argument('stage',choices=['place','route']);a=ap.parse_args()
    run(a.vivado,a.pre,a.runs,a.primary_checkpoint,a.case,a.stage)
