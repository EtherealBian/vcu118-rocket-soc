#!/usr/bin/env python3
"""Join observed B2-to-S0/S1 redirects to *dynamic* architectural instructions."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import runpy
import struct

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'scripts'
BUILD = runpy.run_path(str(SCRIPTS/'test-strict-redirects.py'))
REPLAY = runpy.run_path(str(SCRIPTS/'review-strict-user-replay.py'))
PROFILE = runpy.run_path(str(SCRIPTS/'profile-strict-user-window.py'))
TICKET, PC = struct.Struct('<II'), struct.Struct('<I')
BR, INDIRECT = 1, 3  # sealed BOOM ALUUnit io_brinfo_cfi_type


def digest(data):
    return sha256(data).hexdigest()


def signed(v, bits):
    return v-(1 << bits) if v & (1 << (bits-1)) else v


def decode(pc, op):
    raw, size, _ = op
    w = int(raw, 16)
    if size == 4 and w & 127 == 0x63:
        off = ((w >> 31) << 12 | ((w >> 7) & 1) << 11 |
               ((w >> 25) & 63) << 5 | ((w >> 8) & 15) << 1)
        return BR, pc+signed(off, 13)
    if size == 2 and w & 3 == 1 and w >> 13 in (6, 7):
        off = (((w >> 12) & 1) << 8 | ((w >> 5) & 3) << 6 | ((w >> 2) & 1) << 5 |
               ((w >> 10) & 3) << 3 | ((w >> 3) & 3) << 1)
        return BR, pc+signed(off, 9)
    if ((size == 4 and w & 0x707f == 0x67) or
            (size == 2 and w & 0xe07f == 0x8002 and (w >> 7) & 31)):
        return INDIRECT, None
    return 0, None


def redirects(text, window):
    events = {}
    prev = window['mret_tick']
    for line in text.splitlines():
        cols = line.split()
        if len(cols) != 7 or not all(x.isascii() and x.isdecimal() for x in cols):
            raise ValueError('malformed redirect')
        tick, ticket, src, dst, kind, taken, size = map(int, cols)
        if (not prev < tick <= window['user_ecall_trap_tick'] or ticket in events or
                not 0 < (ticket >> 7) < tick or size not in (2, 4) or kind not in (BR, INDIRECT) or
                taken not in (0, 1) or (src | dst) & 1 or (kind == INDIRECT and not taken)):
            raise ValueError('unexpected B2 metadata, chronology or duplicate allocation')
        events[ticket] = (tick, src, dst, kind, taken, size)
        prev = tick
    if not events:
        raise ValueError('empty B2 capture')
    return events


def spread(counts):
    """Nearest-rank percentiles; support signed differences without truncating."""
    n = sum(counts.values())
    if not n:
        return None
    keys = sorted(counts)
    def rank(p):
        end = (n*p+99)//100
        acc = 0
        for value in keys:
            acc += counts[value]
            if acc >= end:
                return value
    return dict(n=n, min=keys[0], p50=rank(50), p95=rank(95), max=keys[-1])


class DirectionShadow:
    """Retire-time, correct-path-only lower-cost comparators, NOT replacing the RTL predictor."""
    def __init__(self):
        self.bim = bytearray([1])*1024
        self.hist = bytearray(256)
        self.local = bytearray([1])*1024
        self.wrong = {'bimodal': [0]*4, 'local4': [0]*4}

    def update(self, pc, taken, rnd):
        key = pc >> 1
        idx, hidx = key & 1023, key & 255
        ctx = ((key & 63) << 4) | self.hist[hidx]
        for table, address, name in ((self.bim, idx, 'bimodal'), (self.local, ctx, 'local4')):
            value = table[address]
            self.wrong[name][rnd] += (value >= 2) != taken
            table[address] = min(3, value+1) if taken else max(0, value-1)
        self.hist[hidx] = ((self.hist[hidx] << 1) | taken) & 15


def cohort(pcs, tickets, text, w, ops, oracle):
    events = redirects(text, w)
    seen = set()
    total = Counter(); by_pc = Counter(); by_fn = Counter(); taken_counts = Counter()
    rounds = [0]*4; visits = [0]*4; pc_rounds = defaultdict(lambda: [0]*4)
    shadow = DirectionShadow()
    retired_taken = Counter()
    kinds = {pc: decode(pc, op) for pc, op in ops.items()}
    timings = {k: Counter() for k in ('branch_commit_minus_b2', 'next_commit_minus_b2', 'next_dispatch_minus_b2')}
    prev_alloc = [-1]*128
    last_tick, last_slot, rnd = -1, -1, 0
    n = w['user_window_instructions']; cuts = w['fence_ticks']
    if len(pcs) != n*4 or len(tickets) != n*8:
        raise ValueError('ticket/PC trace size')
    for i, ((pc,), (tick, ticket)) in enumerate(zip(PC.iter_unpack(pcs), TICKET.iter_unpack(tickets))):
        slot, alloc = ticket & 127, ticket >> 7
        if (not 0 < alloc < tick or alloc <= prev_alloc[slot] or not cuts[0] <= tick <= cuts[-1] or
                tick < last_tick or (tick == last_tick and (slot//4 != last_slot//4 or slot <= last_slot))):
            raise ValueError('invalid ROB allocation or retirement order')
        prev_alloc[slot] = alloc
        last_tick, last_slot = tick, slot
        if pc == PROFILE['NEXT']:
            rnd += 1
        if (rnd >= 4 or (not visits[rnd] and tick != cuts[rnd]) or
                (i == 0) != (pc == PROFILE['BEGIN'])):
            raise ValueError('round entry mismatch')
        visits[rnd] += 1; total[pc] += 1
        actual_kind, target = kinds[pc]
        if actual_kind == BR:
            successor = PC.unpack_from(pcs, 4*(i+1))[0] if i+1 < n else PROFILE['END']
            fall = pc+ops[pc][1]
            if target == fall or successor not in (target, fall):
                raise ValueError('ambiguous or invalid conditional successor in pinned ELF')
            retired_taken[pc] += successor == target
            shadow.update(pc, successor == target, rnd)
        if ticket not in events:
            continue
        b2, src, dst, kind, taken, size = events[ticket]
        op = ops[pc]
        if i+1 < n:
            (succ,) = PC.unpack_from(pcs, 4*(i+1))
            succ_tick, succ_ticket = TICKET.unpack_from(tickets, 8*(i+1))
            timings['next_dispatch_minus_b2'][(succ_ticket >> 7)-b2] += 1
        else:
            succ, succ_tick = PROFILE['END'], cuts[-1]
        if (src != pc or actual_kind != kind or size != op[1] or dst != succ or
                (kind == BR and (target if taken else pc+size) != dst)):
            raise ValueError('B2 source/size/class/direction/target mismatches ELF or ordered successor')
        seen.add(ticket); by_pc[pc] += 1; rounds[rnd] += 1; pc_rounds[pc][rnd] += 1
        taken_counts[pc] += taken
        name, = [s for lo, hi, s in PROFILE['SYMS'] if lo <= pc < hi]
        by_fn[name] += 1
        timings['branch_commit_minus_b2'][tick-b2] += 1
        timings['next_commit_minus_b2'][succ_tick-b2] += 1
    if visits != w['by_round_instructions'] or not seen:
        raise ValueError('retirement cohort incomplete')
    counts = {}
    for name, kind in [('conditional', BR), ('indirect', INDIRECT)]:
        eligible = [p for p in total if kinds[p][0] == kind]
        counts[name] = dict(retired=sum(total[p] for p in eligible), matched=sum(by_pc[p] for p in eligible))
    for pc in total:
        mnemonic = ops[pc][2]
        if ((kinds[pc][0] == INDIRECT) != (mnemonic in ('jalr', 'c.jr', 'c.jalr')) or
                (kinds[pc][0] == BR) != (PROFILE['group'](mnemonic) == 'conditional_branch')):
            raise ValueError('control-flow opcode classification disagrees with disassembly')
    if (counts['conditional']['retired'] != oracle['by_kind']['conditional_branch'] or
            sum(x['matched'] for x in counts.values()) != len(seen)):
        raise ValueError('unreconciled control-flow denominator')
    def hotspot(pc):
        name, = [s for lo, hi, s in PROFILE['SYMS'] if lo <= pc < hi]
        return dict(pc=hex(pc), function=name, op=ops[pc][2], matched=by_pc[pc],
                    matched_taken=taken_counts[pc], retired=total[pc], by_round=pc_rounds[pc],
                    retired_taken=retired_taken[pc] if kinds[pc][0] == BR else total[pc])
    return dict(all_user_b2=len(events), not_joined_to_hot_retirement=len(events)-len(seen),
                matched=len(seen), matched_by_round=rounds, by_kind=counts,
                matched_by_function=dict(by_fn.most_common()),
                architectural_direction_shadow_misses_by_round=shadow.wrong,
                top10_by_matched=[hotspot(p) for p in sorted(by_pc, key=lambda p: (-by_pc[p], p))[:10]],
                intervals={k: spread(v) for k, v in timings.items()})


def negative_controls(raw, w, ops, ref):
    # Corrupt private captured rows in memory, preserving chronology, encoding, and all guest traces.
    text = raw['redirects'].decode('ascii')
    parsed = redirects(text, w)
    key = next(t for _, t in TICKET.iter_unpack(raw['tickets']) if t in parsed)
    lines = text.splitlines(); i = next(i for i, line in enumerate(lines) if int(line.split()[1]) == key)
    for field in (2, 3):
        cols = lines[i].split(); cols[field] = str(int(cols[field]) ^ 2)
        changed = lines.copy(); changed[i] = ' '.join(cols)
        try:
            cohort(raw['pc'], raw['tickets'], '\n'.join(changed), w, ops, ref)
        except ValueError as err:
            if 'mismatches ELF or ordered successor' not in str(err):
                raise
        else:
            raise ValueError('corrupt captured source/target accepted')
    return ['matched_source_bit1_rejected', 'matched_target_bit1_rejected']


def review(out, elf, objdump):
    lock = json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes())
    oracle = json.loads(REPLAY['ORACLE'].read_bytes()); data = elf.read_bytes()
    if digest(data) != PROFILE['ELF'] or not PROFILE['ELF'] == lock['elf_sha256'] == oracle['elf_sha256']:
        raise ValueError('wrong ELF or oracle')
    ops = PROFILE['disassemble'](objdump, elf, data)
    cpp = BUILD['instrument']((ROOT/'tests/mega_user_replay.cpp').read_text()).encode()
    inputs = json.loads((out/'inputs.json').read_bytes())
    want = {**lock['shared_inputs'], **{k:v for k,v in lock['designs']['stock'].items() if k != 'model'},
            'strict_redirects.hpp': digest(BUILD['HEADER'].read_bytes()), 'replay.cpp': digest(cpp),
            'model': digest((out/'model').read_bytes())}
    if inputs != want or (out/'replay.cpp').read_bytes() != cpp:
        raise ValueError('comparison model or probe identity mismatch')
    rows = {}
    for seed in BUILD['LIB']['SEEDS']:
        ref = oracle['results'][seed]
        raw = {k: (out/(seed+'.'+k)).read_bytes() for k in ('pc', 'tickets', 'redirects', 'events', 'uart')}
        sums = {k: digest(v) for k, v in raw.items()}
        w = REPLAY['inspect'](raw['events'].decode(), raw['uart'], raw['pc'], ref, include_widths=True)
        if w != lock['matched_windows'][seed] or any(sums[k] != v for k,v in lock['evidence'][seed].items()):
            raise ValueError('probes changed stock reference')
        rows[seed] = dict(cohort(raw['pc'], raw['tickets'], raw['redirects'].decode('ascii'), w, ops, ref),
                          private_capture_fault_checks=negative_controls(raw, w, ops, ref), sha256=sums)
    return dict(scope=('Four-round Sv39 stock BOOM snapshot replay. B2 events observed in U mode and joined '
                       'by allocation edge and ROB slot to hot architectural instructions. Not all frontend '
                       'redirects or a cycle savings estimate; not full Linux, STA or board throughput.'),
                elf_sha256=PROFILE['ELF'], inputs=inputs, results=rows)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'elf', 'objdump'):
        ap.add_argument(name, type=Path)
    args = ap.parse_args()
    print(json.dumps(review(args.run, args.elf, args.objdump), indent=2))
