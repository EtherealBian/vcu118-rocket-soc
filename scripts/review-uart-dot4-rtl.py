#!/usr/bin/env python3
"""Require the whole simulated UART epoch and one completion record; never a board result."""
import argparse
import json
from pathlib import Path
import re
from dotbench_report import review


def inspect(mode, lines):
    if mode not in ('uart5-dotbench','uart5-dot4') or len(lines)<6 or lines[:2]!=['UART5_READY v1','UART5_HANDOFF'] or lines[-2]!='':
        raise ValueError('missing or malformed ROM epoch')
    pattern=(rf'ROCKET_RTL_PASS mode={mode} cycles=([1-9]\d*) sectors_started=0 '
             r'tl_read_transactions=([1-9]\d*) tl_write_transactions=(\d+) \(behavioral RAM/card, no physical DDR\)')
    m=re.fullmatch(pattern,lines[-1])
    if not m:raise ValueError('invalid model completion')
    result=dict(mode=mode,scope='Rocket ChipTop with modeled external RAM/card',cycles=int(m[1]),sd_commands=0,tl_reads=int(m[2]),tl_writes=int(m[3]))
    guest=lines[2:-2]
    if mode=='uart5-dotbench':result['dot_benchmark']=review(guest)
    elif guest!=['DOT4_MMIO_START','DOT4_MMIO_PASS vectors=257 protocol_errors_checked=2']:raise ValueError('unexpected Dot4 guest result')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode');p.add_argument('transcript',type=Path);a=p.parse_args()
    print(json.dumps(inspect(a.mode,a.transcript.read_text(encoding='ascii').splitlines()),indent=2))
