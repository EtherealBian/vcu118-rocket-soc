#!/usr/bin/env python3
"""Move the four loop-repair bypass enables across the existing F2/F3 edge.

Derive an isolated overlay from the sealed 175 MHz board inputs. No in-place
changes, clock/constraint changes, or hardware access. The other consumers of
io_update_idx and io_update_repair (training and F2 bypass) stay untouched.
"""
import argparse
from hashlib import sha256
from pathlib import Path

KIT = 'b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'
BANK = 'LoopBranchPredictorBank'
COL = 'LoopBranchPredictorColumn'
HASHES = {BANK: 'c00622a25f75de06f297eac49daf832871cc0726a22c7411610bd98d6f96eb41',
          COL: 'd0ac014f0e323eae279ac8260ac6ae4c2b8d3c52628d1addea887c69991c8900'}


def sealed(kit):
    lock = (kit/'CANDIDATE.sha256').read_bytes()
    if sha256(lock).hexdigest() != KIT:
        raise ValueError('unexpected board kit')
    result = {}
    for n, digest in HASHES.items():
        raw = (kit/'rtl'/(n+'.sv')).read_bytes()
        if sha256(raw).hexdigest() != digest or f'{digest}  rtl/{n}.sv' not in lock.decode().splitlines():
            raise ValueError('unexpected input: '+n)
        result[n] = raw.decode()
    return result


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('expected exactly one site: '+old)
    return text.replace(old, new)


def derive(src):
    b, c = src[BANK], src[COL]
    b = once(b, '  reg  [35:0]  s1_update_idx;', '  reg [3:0] vcu_f3_repair_bypass;\n  reg  [35:0]  s1_update_idx;')
    b = once(b, '    s1_update_idx <=', '''    // These are the D inputs of the original F3 operands, sampled on this same edge.
    vcu_f3_repair_bypass <= {4{(s2_idx == io_update_bits_pc[39:4]) & io_update_valid & io_update_bits_is_repair_update}} & io_update_bits_br_mask;
    s1_update_idx <=''')
    for i in range(4):
        site = f'  LoopBranchPredictorColumn columns_{i} ('
        line, sep, rest = b.partition(site)[2].partition('\n')
        if not sep or '.clock' not in rest.splitlines()[0]:
            raise ValueError('unexpected column ports')
        b = once(b, site+line+'\n', site+line+f'\n    .vcu_f3_repair_bypass (vcu_f3_repair_bypass[{i}]),\n')
    c = once(c, '  input         io_update_repair,', '  input         vcu_f3_repair_bypass,\n  input         io_update_repair,')
    c = once(c, 'io_update_repair & io_update_idx == f3_scnt_REG ?', 'vcu_f3_repair_bypass ?')
    # Remove only the dead 36-bit F3 copy, including its generated random init.
    lines = c.splitlines(keepends=True)
    if len([row for row in lines if 'f3_scnt_REG' in row]) != 3:
        raise ValueError('unexpected remaining use of F3 index')
    return {BANK:b, COL:''.join(row for row in lines if 'f3_scnt_REG' not in row)}


def emit(kit, out):
    files = derive(sealed(kit))
    out.mkdir(exist_ok=False)
    for name, text in files.items():
        (out/(name+'.sv')).write_bytes(text.encode())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('kit', type=Path)
    p.add_argument('fresh_overlay', type=Path)
    args = p.parse_args()
    emit(args.kit, args.fresh_overlay)
