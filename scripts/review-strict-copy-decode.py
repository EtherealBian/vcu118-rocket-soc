#!/usr/bin/env python3
"""Match stock pre-edge decode witnesses to retired reversal-loop instructions."""
import argparse
from collections import Counter
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import runpy
import struct
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
RUN = runpy.run_path(str(ROOT/'scripts/test-strict-copy-decode.py'))
ENTRY, COPY, LOAD, STORE, MOVE, BR = range(0x13b60, 0x13b6c, 2)
ENC = {COPY: 0x00e00433, LOAD: 0x00043703}
PC, TICKET = struct.Struct('<I'), struct.Struct('<II')


class Dec(NamedTuple):
    key: int
    tick: int
    inst: int
    rvc: int
    exception: int
    sfb: int
    fp: int
    dst_valid: int
    dst_type: int
    src1_type: int
    src2_type: int
    dst: int
    src1: int
    src2: int
    ldq: int
    stq: int
    amo: int
    cmd: int


def records(lines):
    widths = (32, 32, 32, 1, 1, 1, 1, 1, 2, 2, 2, 6, 6, 6, 1, 1, 1, 5)
    prev = None
    for line in lines:
        c = line.split()
        if len(c) != 18 or not all(v.isascii() and v.isdecimal() for v in c):
            raise ValueError('invalid decode record')
        d = Dec(*map(int, c))
        if any(v >= 1 << n for v,n in zip(d, widths)) or not 0 < d.tick < (d.key >> 7):
            raise ValueError('invalid field or decode/dispatch edge')
        if prev and (d.key <= prev.key or d.tick < prev.tick or
                     (d.tick == prev.tick and d.key % 4 <= prev.key % 4) or
                     ((d.key >> 7) == (prev.key >> 7) and d.key // 4 != prev.key // 4)):
            raise ValueError('duplicate or out-of-order decode/dispatch witness')
        prev = d
        yield d


def adjacent(a,b):
    return a.tick == b.tick and b.key % 4 == a.key % 4 + 1


def eligible(m,l):
    # Mirror the data-independent RenameStage candidate guard; rvc itself is not a guard.
    return bool(adjacent(m,l) and not (m.exception or l.exception or m.sfb or l.sfb or m.fp or l.fp)
                and m.dst_valid and m.dst_type == m.src1_type == m.src2_type == 0
                and (m.inst & 0xfe0ff07f) == 0x33 and m.src1 == 0
                and m.dst == ((m.inst >> 7) & 31) and m.src2 == ((m.inst >> 20) & 31)
                and m.dst and m.src2 and m.dst != m.src2
                and (l.inst & 0x7f) == 3 and ((l.inst >> 12) & 7) != 7
                and l.ldq and not (l.stq or l.amo or l.cmd) and l.src1_type == l.dst_type == 0
                and l.src1 == ((l.inst >> 15) & 31) and l.src1 == m.dst)


def analyse(raw, lines, anchor):
    pcs, tickets = raw['pc'], raw['tickets']
    if len(pcs) % 4 or len(tickets) != 2*len(pcs):
        raise ValueError('malformed retirement trace')
    def pc(i): return PC.unpack_from(pcs, 4*i)[0]
    rows = records(lines)
    def witness(i):
        d = next(rows, None)
        rt, key = TICKET.unpack_from(tickets, 8*i)
        if d is None or d.key != key or (d.key >> 7) >= rt or not d.rvc or d.inst != ENC[pc(i)]:
            raise ValueError('retired ticket, instruction or edge differs from witness')
        return d
    amount = Counter()
    names = ('yes_yes','yes_no','no_yes','no_no')  # Adjacent at decode? Adjacent at dispatch?
    cross = dict.fromkeys(names, 0)
    lanes = dict.fromkeys(('0_to_1','1_to_2','2_to_3'), 0)
    last_branch = None
    for i,(p,) in enumerate(PC.iter_unpack(pcs)):
        if p != BR: continue
        if i < 4 or 4*(i+1) >= len(pcs) or tuple(pc(j) for j in range(i-3,i+1)) != (LOAD,STORE,MOVE,BR):
            raise ValueError('incomplete reversal body')
        before, after = pc(i-4), pc(i+1)
        if after not in (COPY, BR+2): raise ValueError('unexpected reversal successor')
        amount['branches'] += 1
        amount['taken' if after == COPY else 'exits'] += 1
        if before == COPY:
            if last_branch != (i-5, True): raise ValueError('copy has no preceding taken backedge')
            m,l = witness(i-4), witness(i-3)
            same_dis = (m.key >> 7) == (l.key >> 7)
            if same_dis and (l.key != m.key+1 or m.key//4 != l.key//4):
                raise ValueError('paired dispatch was not in adjacent lanes')
            amount['same_dispatch' if same_dis else 'separate_dispatch'] += 1
            same_dec = adjacent(m,l)
            cross[('yes_' if same_dec else 'no_') + ('yes' if same_dis else 'no')] += 1
            if eligible(m,l): lanes[f'{m.key%4}_to_{l.key%4}'] += 1
        elif before == ENTRY and not (last_branch and last_branch[1]):
            witness(i-3); amount['entry_load_without_copy'] += 1
        else:
            raise ValueError('unexpected reversal loop entry')
        last_branch = (i, after == COPY)
    if not last_branch or last_branch[1] or next(rows, None) is not None:
        raise ValueError('missing complete loop or unexpected record')
    if any(amount[k] != anchor[k] for k in ('branches','taken','exits','same_dispatch','separate_dispatch')) or not (
        sum(cross.values()) == amount['taken'] and amount['entry_load_without_copy'] == amount['exits']):
        raise ValueError('wrong recurrence, dispatch or entry counts')
    return dict(counts=dict(sorted(amount.items())), adjacent_decode_by_adjacent_dispatch=cross,
                guard_matches=sum(lanes.values()), guard_matches_by_decode_lane=lanes)


def wiring(kit, target_hash):
    # Check the measurement taps against the same sealed RTL, not names from another width.
    rtl = kit/'rtl'
    core = (rtl/'BoomCore.sv').read_text()
    tile = (rtl/'BoomTile.sv').read_text()
    rename = (rtl/'RenameStage.sv').read_text()
    ports = core.split('RenameStage rename_stage (',1)[1].split(');',1)[0]
    def port(text, name, driver):
        if not re.search(r'\.'+name+r'\s+\('+re.escape(driver)+r'\)', text):
            raise ValueError('unexpected connection: '+name)
    for pin,driver in [('fetchpacket_ready','dec_ready'),('redirect_flush','rename_stage_io_kill')]:
        name='io_ifu_'+pin
        port(tile,name,'_core_'+name)
        if 'assign '+name+' = '+driver+';' not in core: raise ValueError('changed '+name)
    port(ports,'io_kill','rename_stage_io_kill'); port(ports,'io_dis_ready','~dis_stalls_3')
    fields = ('inst','uopc','ftq_idx','is_rvc','exception','is_sfb','fp_val','ldst_val','dst_rtype',
              'lrs1_rtype','lrs2_rtype','ldst','lrs1','lrs2','uses_ldq','uses_stq','is_amo','mem_cmd')
    for i in range(4):
        port(ports,f'io_dec_fire_{i}',f'dec_fire_{i}' if i<3 else 'dec_ready')
        reg = 'r_uop_' + (f'{i}_' if i else '')
        for f in fields:
            src = f'io_dec_uops_{i}_{f}'
            if f in ('inst','ftq_idx','uopc'): port(ports,src,f'_decode_units_{i}_io_deq_uop_{f}')
            if f'{reg}{f} <= {src};' not in rename: raise ValueError('not a direct registered field: '+src)
    gen = runpy.run_path(str(ROOT/'scripts/test-copy-load-rename.py'))['candidate']
    if sha256(gen(rename).encode()).hexdigest() != target_hash:
        raise ValueError('not the guard of the sealed functional candidate')


def review(kit, obj, guest, previous, out, elf):
    _, prior, paths, pins, generated = RUN['inputs'](kit,obj,guest,previous,out)
    inputs = json.loads((out/'inputs.json').read_bytes())
    if pins() != inputs or any(paths[k].read_bytes() != data for k,data in generated.items()):
        raise ValueError('probe, selection or sealed input mismatch')
    def doc(name): return json.loads((ROOT/'docs'/name).read_bytes())
    anchor = doc('perf-strict-reversal.json'); identity = doc('perf-strict-user-window.json')['elf_sha256']
    target_hash = doc('perf-copy-load-model.json')['changed']['rtl/RenameStage.sv']
    wiring(kit,target_hash)
    binary = elf.read_bytes()
    if (sha256(binary).hexdigest() != identity or identity != anchor['elf_sha256'] or
            binary[COPY-0x10000:LOAD+2-0x10000] != bytes.fromhex('3a841860')):
        raise ValueError('different ELF or compressed encodings')
    results = {}
    for seed in RUN['LIB']['SEEDS']:
        raw = RUN['CAP']['checked_capture'](out,seed,prior)
        path = out/(seed+'.decode'); data = path.read_bytes()
        results[seed] = dict(**analyse(raw,StringIO(data.decode('ascii')),anchor['results'][seed]['counts']),
                             decode_sha256=sha256(data).hexdigest())
    return dict(scope='Stock four-wide BOOM, four rounds per seed from user snapshots. Guard opportunities for one retired loop, not cycles saved, a candidate result or an FPGA score.',
                elf_sha256=identity, stock_kit_sha256=inputs['CANDIDATE.sha256'],
                candidate_rename_sha256=target_hash, probe_sha256=inputs['strict_copy_decode.hpp'], model_sha256=inputs['model'], results=results)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ('kit','obj','guest','previous','out','elf'): ap.add_argument(k,type=Path)
    ap.add_argument('--expect',type=Path,help='fail if even a raw trace hash differs from the saved summary')
    a = ap.parse_args(); result = review(*(getattr(a,k).resolve() for k in ('kit','obj','guest','previous','out','elf')))
    if a.expect and result != json.loads(a.expect.read_bytes()): raise ValueError('different saved decode evidence')
    print(json.dumps(result, indent=2))
