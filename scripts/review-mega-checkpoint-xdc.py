#!/usr/bin/env python3
"""Inventory the serialized XDC commands in two specific post-opt checkpoints.

Reads small XML/XDC archive entries, never opens a second Vivado design. Equal
selectors do not imply equal matching cells, constraint coverage or timing.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

TOP = 'VCU118FPGATestHarness'
TYPES = {'XDC':'', 'XDC_BOARD':'_board', 'XDC_EARLY':'_early', 'XDC_LATE':'_late'}
INPUTS = (
    ('bea90f70e656a177a9744b879b9edb2a9229f7b9087a5cdf36ca58685affc5f3', 'split5h-impl-a', 'split5h-a', 'BufferedDebugRocketVCU118Config'),
    ('98e6d4f6c545a4f0f07c0618dad28e5de23dc9330ff98bc2cc81d2038a54db5f', 'perf-mega175-split-impl-d', 'perf-mega175-split-board-d', 'Perf175MegaBoomVCU118Config'))


def commands(raw, names):
    run, kit, cfg = names
    result=[]; rules=Counter(); scope='top'
    for line in raw.decode('ascii').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line.startswith('set_property SRC_FILE_INFO '):
            if not re.fullmatch(r'set_property SRC_FILE_INFO \{[^{};\n]+\} \[current_design\]',line):
                raise ValueError('unexpected source-file metadata')
            # Normalize path fields only, not scoped_inst, order, file names,
            # the target or other options. The three shell inputs belong to
            # different generator config names but were compared separately.
            def paths(m):
                val=m[2].replace('/'+run+'/', '/$run/').replace('/'+kit+'/', '/$kit/')
                val=val.replace('.'+cfg+'.shell.', '.$config.shell.')
                val=re.sub(r'/\.Xil/Vivado-[0-9]+-[^/]+/dbg_hub_CV\.0/', '/.Xil/$session/dbg_hub_CV.0/', val)
                return m[1]+':'+val
            line=re.sub(r'\b(cfile|rfile|rxprname):([^\s}]+)',paths,line)
        elif line.startswith('create_waiver '):
            # Keep complete selectors, directions, rule, owner, reason and tags.
            stamp=r' -timestamp "(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} [ 0-9]?\d \d{2}:\d{2}:\d{2} GMT \d{4}"$'
            line,n=re.subn(stamp,' -timestamp "<time>"',line)
            if n!=1:raise ValueError('unexpected waiver timestamp')
            m=re.match(r'create_waiver -type (\w+) -id \{([\w-]+)\} ',line)
            if not m:raise ValueError('unrecognized waiver declaration')
            rules[(scope,m[1],m[2])]+=1
        elif line.startswith('current_instance '):
            scope=line.split(' ',1)[1]
            if scope=='-quiet':scope='top'
        result.append(line)
    return result, rules


def read(dcp, identity):
    with dcp.open('rb') as stream:
        h=sha256()
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    if h.hexdigest()!=identity[0]:raise ValueError('different post-opt checkpoint')
    files={}; rules=Counter()
    with ZipFile(dcp) as z:
        xml=ET.fromstring(z.read('dcp.xml'))
        for key,wanted in [('Top',TOP),('PRODUCT','Vivado v2024.2 (64-bit)'),('Part','xcvu9p-flga2104-2L-e'),('OutOfContext','0')]:
            if [el.get('Name') for el in xml.findall(key)]!=[wanted]:raise ValueError('wrong design '+key)
        names=[n for n in z.namelist() if n.endswith('.xdc')]; want=[TOP+s+'.xdc' for s in TYPES.values()]
        if sorted(names)!=sorted(want):raise ValueError('unexpected serialized XDC file set')
        for typ,suffix in TYPES.items():
            n=TOP+suffix+'.xdc'
            if [el.get('Name') for el in xml.findall('File') if el.get('Type')==typ]!=[n]:raise ValueError('incorrect XDC manifest entry')
            raw=z.read(n); lines,waive=commands(raw,identity[1:]); rules.update(waive)
            files[typ]=(lines,sha256(raw).hexdigest())
    return files,rules


def review(rocket,mega):
    (ref,w0),(candidate,w1)=(read(p,i) for p,i in zip((rocket,mega),INPUTS))
    if w0!=w1:raise ValueError('different scoped waiver rules')
    files={}; counts=Counter()
    for typ in TYPES:
        a,ha=ref[typ];b,hb=candidate[typ]
        if a!=b:raise ValueError('different ordered checkpoint XDC commands: '+typ)
        c=Counter(line.split()[0] for line in b); counts.update(c)
        files[typ]=dict(rocket_xdc_sha256=ha,mega_xdc_sha256=hb,ordered_command_count=len(b),
                        common_normalized_commands_sha256=sha256(('\n'.join(b)+'\n').encode()).hexdigest())
    return dict(scope='Serialized Vivado post-opt XDC comparison (not routed STA, exception coverage, CDC/DRC signoff or programming permission). Matching commands may resolve to different cells or pins.',
                post_opt_dcp_sha256=[v[0] for v in INPUTS],ignored_differences='Blank and full comment lines, run/kit/config and debug-session components in SRC_FILE_INFO paths, and create_waiver timestamp only.',
                xdc_files=files,command_counts=dict(sorted(counts.items())),
                waiver_declarations=[dict(scope=k[0],type=k[1],rule=k[2],count=v) for k,v in sorted(w1.items())])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rocket',type=Path);p.add_argument('mega',type=Path);a=p.parse_args()
    print(json.dumps(review(a.rocket,a.mega),indent=2))
