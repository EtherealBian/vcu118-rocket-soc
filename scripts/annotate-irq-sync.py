#!/usr/bin/env python3
"""Mark only the pinned, three-flop, unreset Rocket synchronizer; preserve every RTL assignment."""
import argparse
import hashlib
from pathlib import Path

EXPECTED='e6b4d14e7ff7fd8ebc9581de9b74edb96a0fb310f86f0b79e0f9ef7b5cb763d2'
ATTRIBUTE=b'(* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) '
NAME='NonSyncResetSynchronizerPrimitiveShiftReg_d3.sv'

def annotated(src):
    if hashlib.sha256(src).hexdigest()!=EXPECTED: raise ValueError('unexpected FIRRTL synchronizer implementation; inspect manually')
    result=src
    for stage in range(3):
        key=f'  reg sync_{stage};'.encode();
        if result.count(key)!=1: raise ValueError('missing or duplicated stage')
        result=result.replace(key, b'  '+ATTRIBUTE+key[2:])
    if result.replace(ATTRIBUTE,b'')!=src: raise ValueError('changed content other than register attributes')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('fresh_output',type=Path);a=p.parse_args()
    data=annotated((a.kit/'rtl'/NAME).read_bytes());a.fresh_output.mkdir(parents=True,exist_ok=False)
    (a.fresh_output/NAME).write_bytes(data);print('ANNOTATED_SYNC_LEAF_SHA256',hashlib.sha256(data).hexdigest())
