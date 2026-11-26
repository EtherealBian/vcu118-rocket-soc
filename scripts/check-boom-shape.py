#!/usr/bin/env python3
"""Count one reachable hart, scalar decoders and ROB architectural commit lanes in firtool RTL."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def check(root, width, rob_entries=None):
    hashes = {}
    def body(name):
        raw = (root / (name + '.sv')).read_bytes()
        hashes[name+'.sv'] = hashlib.sha256(raw).hexdigest()
        text = re.sub(r'//[^\n]*|/\*.*?\*/', '', raw.decode(), flags=re.S)
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
    rb = body(rob)
    for signal in ('valids', 'arch_valids'):
        port = r'io_commit_' + signal + r'_(\d+)'
        ends = re.findall(r'\.' + port + r'\s*\(\s*\w+\s*\)', conn)
        drives = re.findall(r'\bassign\s+' + port + r'\s*=', rb)
        if sorted(map(int, ends)) != list(range(width)) or sorted(map(int, drives)) != list(range(width)):
            raise ValueError(f'unconnected or extra ROB {signal} lanes')
    valid_regs = re.findall(r'(?m)^\s*reg\s+(rob_val_\d+(?:_\d+)?);', rb)
    drivers = set(re.findall(r'\b(rob_val_\d+(?:_\d+)?)\s*<=', rb))
    rows, rem = divmod(len(valid_regs), width)
    expected = {f'rob_val_{bank}_{row}' if bank else f'rob_val_{row}' for bank in range(width) for row in range(rows)}
    if (not rows or rem or expected != set(valid_regs) or expected != drivers
            or (rob_entries is not None and len(valid_regs) != rob_entries)):
        raise ValueError('unexpected ROB valid storage bank, row, driver or capacity')
    return {'rob_banks':width, 'rob_rows_per_bank':rows, 'rob_entries':len(valid_regs), 'rtl_sha256':hashes, 'core': '.'.join(path), 'decoder_count': width, 'architectural_commit_lanes': width,
            'scope': 'generated structure only; not sustained IPC, pipeline depth, clock signoff or board performance'}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('rtl', type=Path)
    ap.add_argument('--width', type=int, required=True, choices=(2, 3, 4))
    ap.add_argument('--rob-entries', type=int, help='expected total number of driven ROB valid bits')
    a = ap.parse_args()
    print(json.dumps(check(a.rtl, a.width, a.rob_entries), indent=2))
