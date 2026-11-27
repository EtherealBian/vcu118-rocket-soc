#!/usr/bin/env python3
"""Prepare matched registered boundaries for physical comparison of the proven MSHR cuts."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
CASES=('stock','class_local','split_rsp')


def require(ok, why):
    if not ok:
        raise ValueError(why)


def make(archive, out):
    archive=archive.resolve(strict=True)
    require(not out.is_symlink() and not out.exists(), 'need fresh output directory')
    out=out.resolve(); require(out not in archive.parents and archive not in out.parents, 'overlapping dirs')
    ref=json.loads((ROOT/'docs/perf-mega175-mshr-connected.json').read_bytes())
    require(json.loads((archive/'result.json').read_bytes())==ref, 'wrong connected experiment')
    require(all(ref['proofs'][s]['status']=='equivalent' for s in CASES[1:]), 'candidates not equivalent')
    data={}; ports=None
    for label in CASES:
        raw=(archive/(label+'.v')).read_bytes(); require(sha256(raw).hexdigest()==ref['cuts_sha256'][label], 'wrong cut '+label)
        src=raw.decode('ascii'); decl=src.splitlines()[0]; prefix='module top('; suffix=', output [2:0] o);'
        require(decl.startswith(prefix) and decl.endswith(suffix), 'top declaration')
        pins={}
        for port in decl[len(prefix):-len(suffix)].split(', '):
            m=re.fullmatch(r'input (?:\[(\d+):0\] )?(\w+)',port); require(m and m[2] not in pins, 'input declaration'); pins[m[2]]=int(m[1] or 0)+1
        require(list(pins)==sorted(pins) and sum(pins.values())==ref['inputs_bits']==1891, 'wrong input boundary')
        require(ports is None or ports==pins, 'interface changed'); ports=pins
        # Formal miters need unique module names; make hierarchy identical for physical comparison.
        for name in ('mshr','resp'):
            old=name+'_'+label; require(src.count(old)==3, 'unexpected instance/module scope'); src=src.replace(old,name+'_cut')
        data[label+'.v']=src
    names=sorted(ports); vector=lambda w: f'[{w-1}:0] ' if w>1 else ''
    lines=['module boundary(input clk, '+', '.join('input '+vector(ports[n])+'in_'+n for n in names)+', output reg [2:0] result);']
    for n in names:
        lines.extend(['reg '+vector(ports[n])+'q_'+n+';',f'always @(posedge clk) q_{n} <= in_{n};'])
    lines+=['wire [2:0] d;', 'top core('+', '.join(f'.{n}(q_{n})' for n in names)+', .o(d));','always @(posedge clk) result <= d;','endmodule']
    data['boundary.v']='\n'.join(lines)+'\n'; data['clock.xdc']='create_clock -name cpu -period 5.714 [get_ports clk]\n'
    out.mkdir(mode=0o700); hashes={}
    for n,s in data.items():
        b=s.encode('ascii'); (out/n).write_bytes(b); hashes[n]=sha256(b).hexdigest()
    result=dict(scope='Unrouted OOC inputs only; register boundaries are experiment fixtures, not a processor pipeline change.',source_cuts={s:ref['cuts_sha256'][s] for s in CASES},files_sha256=hashes,input_bits=sum(ports.values()),capture_bits=3)
    (out/'bound.json').write_bytes((json.dumps(result,indent=2)+'\n').encode()); return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('archive',type=Path); ap.add_argument('out',type=Path); a=ap.parse_args()
    print(json.dumps(make(a.archive,a.out),indent=2))
