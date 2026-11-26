#!/usr/bin/env python3
"""Count one reachable hart, scalar decoders and ROB architectural commit lanes in firtool RTL."""
import argparse
import json
import re
from pathlib import Path


def check(root, width):
    def body(name):
        text = re.sub(r'//[^\n]*|/\*.*?\*/', '', (root / (name + '.sv')).read_text(), flags=re.S)
        match = re.search(r'(?ms)^\s*module\s+' + re.escape(name) + r'\s*\((.*?)\bendmodule\b', text)
        if not match:
            raise ValueError('missing module: ' + name)
        return match[1]

    def instances(text, module):
        return re.findall(r'(?m)^\s*(' + module + r'(?:_\d+)?)\s+(\w+)\s*\(', text)

    path, parent = ['ChipTop'], body('ChipTop')
    for expected in ('DigitalTop', 'TilePRCIDomain', 'BoomTile', 'BoomCore'):
        found = instances(parent, expected)
        if len(found) != 1:
            raise ValueError(f'expected one reachable {expected}, found {found}')
        name, inst = found[0]
        path.append(inst)
        parent = body(name)
    dec = [inst for _, inst in instances(parent, 'DecodeUnit')]
    if set(dec) != {f'decode_units_{i}' for i in range(width)} or len(dec) != width:
        raise ValueError(f'unexpected decode instances: {dec}')
    robs = instances(parent, 'Rob')
    if len(robs) != 1:
        raise ValueError('expected one ROB')
    rob, name = robs[0]
    conn = re.search(r'\b' + rob + r'\s+' + name + r'\s*\((.*?)\);', parent, re.S)[1]
    for signal in ('valids', 'arch_valids'):
        port = r'io_commit_' + signal + r'_(\d+)'
        ends = re.findall(r'\.' + port + r'\s*\(\s*\w+\s*\)', conn)
        drives = re.findall(r'\bassign\s+' + port + r'\s*=', body(rob))
        if sorted(map(int, ends)) != list(range(width)) or sorted(map(int, drives)) != list(range(width)):
            raise ValueError(f'unconnected or extra ROB {signal} lanes')
    return {'core': '.'.join(path), 'decoder_count': width, 'architectural_commit_lanes': width,
            'scope': 'generated structure only; not sustained IPC, pipeline depth, clock signoff or board performance'}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('rtl', type=Path)
    ap.add_argument('--width', type=int, required=True, choices=(2, 3, 4))
    a = ap.parse_args()
    print(json.dumps(check(a.rtl, a.width), indent=2))
