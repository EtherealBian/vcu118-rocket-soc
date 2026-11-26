#!/usr/bin/env python3
"""Prove that the generated ChipTop's debug clock now uses the stock gate's input net."""
import argparse
from pathlib import Path
import re


def port(instance, name):
    m=re.findall(r'^\s*\.'+name+r'\s*\(\s*(~?[\w\']+)\s*\)', instance, re.M)
    if len(m)!=1:
        raise ValueError(f'missing/ambiguous port: {name}')
    return m[0]


def simple_signal(design, name):
    # firtool inlines named single-use wires after the gate's removal. Resolve
    # only scalar wire aliases / single bitwise inversions, not arbitrary RTL.
    expr=port(design, name)
    seen=set(); inverted=False
    while True:
        if expr.startswith('~'):
            inverted=not inverted; expr=expr[1:]
        if expr in seen: raise ValueError('cyclic alias: '+expr)
        seen.add(expr)
        m=re.findall(r'^\s*wire\s+'+re.escape(expr)+r'\s*=\s*(~?\w+)\s*;',design,re.M)
        if not m: return ('~' if inverted else '')+expr
        if len(m)!=1: raise ValueError('ambiguous alias: '+expr)
        expr=m[0]


def compare(stock, new):
    name='gated_clock_debug_clock_gate'
    m=re.findall(r'\bEICG_wrapper\s+'+name+r'\s*\((.*?)\);', stock, re.S)
    if len(m)!=1 or name in new:
        raise ValueError('expected exactly one original gate and no candidate gate')
    before=port(m[0],'out'); after=port(m[0],'in')
    if port(stock,'debug_clock')!=before or port(new,'debug_clock')!=after or before==after:
        raise ValueError('debug clock was not moved from the exact gate output to its input')
    for signal in ['debug_reset','debug_dmactiveAck']:
        if simple_signal(stock,signal)!=simple_signal(new,signal):
            raise ValueError('unexpected change in '+signal)
    return after


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('stock',type=Path); ap.add_argument('variant',type=Path); a=ap.parse_args()
    print('DEBUG_CLOCK_NOW_USES_ORIGINAL_UNGATED_NET',compare(a.stock.read_text(),a.variant.read_text()))
