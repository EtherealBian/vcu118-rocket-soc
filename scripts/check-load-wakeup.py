#!/usr/bin/env python3
"""Check the speculative and ordinary LSU-to-core links in a stock/candidate firtool pair."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

NAMES = ('spec_ld_wakeup_0_valid', 'spec_ld_wakeup_0_bits', 'ld_miss')
ORDINARY = 'exe_0_iresp_valid'


def single(pattern, text, purpose):
    found = list(re.finditer(pattern, text, re.M | re.S))
    if len(found) != 1:
        raise ValueError('expected exactly one ' + purpose)
    return found[0]


def read_module(rtl, mod):
    data = (rtl / (mod + '.sv')).read_bytes()
    body = re.sub(r'//[^\n]*|/\*.*?\*/', '', data.decode(), flags=re.S)
    content = single(r'^\s*module\s+' + mod + r'\s*\((.*?)\bendmodule\b', body, mod)[1]
    return content, sha256(data).hexdigest()


def check_variant(rtl, speculative):
    modules = {}; hashes = {}
    for mod in ('BoomTile', 'BoomCore', 'LSU'):
        modules[mod], hashes[mod + '.sv'] = read_module(rtl, mod)
    tile, core, lsu = (modules[k] for k in ('BoomTile', 'BoomCore', 'LSU'))
    def instance(kind):
        return single(r'^\s*' + kind + r'\s+\w+\s*\((.*?)\)\s*;', tile, kind + ' instance')[1]
    endpoints = [instance('LSU'), instance('BoomCore')]
    def link(key):
        outp, inp = 'io_core_' + key, 'io_lsu_' + key
        conns = [single(r'\.' + p + r'\s*\(\s*(\w+)\s*\)', t, p + ' binding')[1]
                 for p, t in zip((outp, inp), endpoints)]
        wire = conns[0]
        if wire != conns[1] or wire != '_lsu_' + outp:
            raise ValueError('tile connection mismatch: ' + key)
        single(r'\bwire\s+(?:\[\d+:0\]\s+)?' + wire + r'\s*;', tile, 'tile wire ' + key)
        for kind, pin, module in [('output', outp, lsu), ('input', inp, core)]:
            single(r'\b' + kind + r'\s+(?:\[\d+:0\]\s+)?' + pin + r'\b', module, 'module pin ' + pin)
        rhs = single(r'\bassign\s+' + outp + r'\s*=\s*([^;]+);', lsu, 'LSU driver ' + key)[1]
        # A residual name or tie-off is not evidence of a live link. Require a
        # transaction-dependent reference on the LSU side and an actual core sink.
        if not re.search(r'\b(?:io_\w+|mem_incoming_\w+|spec_ld_succeed_\w+)\b', rhs):
            raise ValueError('no data-driven LSU signal: ' + key)
        if not re.search(r'\.\w+\s*\(\s*' + inp + r'\s*\)', core):
            raise ValueError('no core submodule consumes: ' + key)
    link(ORDINARY)
    for key in NAMES:
        if speculative:
            link(key)
        elif any(re.search(r'(?:io_core_|io_lsu_)' + key + r'\b', t) for t in modules.values()):
            raise ValueError('speculative signal survives: ' + key)
    return dict(speculative_ports=list(NAMES) if speculative else [], ordinary_port=ORDINARY, rtl_sha256=hashes)


def check(stock, nofast):
    return dict(scope='Generated tile interface only. The ordinary integer load response remains connected; this does not prove that a physical critical path is gone, measure cycles, or sign off timing.',
                stock=check_variant(stock, True), no_fast_load=check_variant(nofast, False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('stock', 'nofast'): p.add_argument(arg, type=Path)
    a = p.parse_args(); print(json.dumps(check(a.stock, a.nofast), indent=2))
