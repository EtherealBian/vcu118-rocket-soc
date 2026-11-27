#!/usr/bin/env python3
"""Audit a modeled four-round ChipTop PC window; never compute a board score."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / 'docs/perf-strict-user-window.json'
EPOCH = b'UART5_READY v1\r\nUART5_HANDOFF\r\nK'
MRET = r'MRET tick=(\d+) epc=106b0 ret=1 satp=8 uart_bytes=(\d+)'
EXIT = (r'EXIT start=(\d+) stop=(\d+) cycles=(\d+) u_arch_valid=(\d+) '
        r'mepc=147b4 cause=8 tval=0 lanes=((?:\d+,){5})')
WINDOW = r'WINDOW hot=(\d+) pre=((?:[a-f0-9]+,)*) post=((?:[a-f0-9]+,)*) fences=((?:\d+,){5})'


def csv(text, base=10):
    return [int(x, base) for x in text.split(',') if x]


# The entry stub's MRET asserts arch_valid after prv has already changed to U.
# After END only the JAL and two libc instructions assert valid (the ECALL traps).
OUTER = ([0x800000ec], [0x10f3a, 0x147ac, 0x147b0])


def inspect(events, uart, trace, ref, *, include_widths=False, target_tail=False):
    lines = events.splitlines()
    if len(lines) != 3 or uart != EPOCH:
        raise ValueError('incomplete ROM/result epoch or unexpected events')
    length = 8 if target_tail else 4
    mret = MRET.replace('epc=106b0', 'epc=10af0') if target_tail else MRET
    window_format = WINDOW.replace('{5}', '{9}') if target_tail else WINDOW
    matches = [re.fullmatch(fmt, row) for fmt, row in zip((mret, EXIT, window_format), lines)]
    if not all(matches):
        raise ValueError('missing privilege, ROB or trap witness')
    entry, leave, window = matches
    start, nready = map(int, entry.groups()); repeated, stop, dt, n = map(int, leave.groups()[:4])
    widths = csv(leave[5]); hot = int(window[1]); pre, post = [csv(x, 16) for x in window.groups()[1:3]]
    fences = csv(window[4]); cycles = [y-x for x,y in zip(fences,fences[1:])]
    if (not len(b'UART5_READY v1\r\n') <= nready <= len(EPOCH)-1 or start != repeated or
        stop-start != dt or not start < fences[0] < fences[-1] <= stop or min(cycles) <= 0 or
        sum(widths) != dt or sum(i*k for i,k in enumerate(widths)) != n or
        (pre, post) != OUTER or n != hot+len(pre)+len(post)):
        raise ValueError('inconsistent cycle accounting or unexpected out-of-window PC')
    sha = hashlib.sha256(trace).hexdigest()
    if len(trace) != hot*4 or hot != ref['dynamic_instructions'] or sha != ref['ordered_pc_sha256']:
        raise ValueError('ordered ROB PCs differ from independently expanded emulator trace')
    rounds = [0]; lists = [0]
    for i,(pc,) in enumerate(struct.iter_unpack('<I',trace)):
        if ((pc == 0x106b0) != (not target_tail and i == 0) or pc == 0x10f3a or
                (target_tail and i == 0 and pc != 0x10af0)):
            raise ValueError('wrong PC fence')
        if pc == 0x10af0 and i:
            rounds.append(0); lists.append(0)
        rounds[-1] += 1; lists[-1] += pc == 0x13b0c
    if rounds != ref['by_round'] or lists != [2]*length:
        raise ValueError('wrong per-round instruction or list-call counts')
    result = dict(ordered_pc_sha256=sha, user_window_instructions=hot,
                user_window_cycles=fences[-1]-fences[0], by_round_cycles=cycles,
                by_round_instructions=rounds, fence_ticks=fences,
                mret_tick=start, user_ecall_trap_tick=stop, privilege_interval_cycles=dt,
                prefix_arch_valid_pc=[hex(x) for x in pre], suffix_arch_valid_pc=[hex(x) for x in post])
    if include_widths:
        # This histogram covers the MRET-to-trap interval, not just the user PC fences.
        result['privilege_interval_cycles_by_retired_width_0_to_4'] = widths
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--role', choices=('stock', 'lvt'), default='stock')
    args = parser.parse_args()
    ref = json.loads(ORACLE.read_bytes()); results = {}
    for seed in ('performance', 'validation'):
        files = [args.run/(seed+'.'+suffix) for suffix in ('events', 'uart', 'pc')]
        results[seed] = inspect(files[0].read_text(), files[1].read_bytes(), files[2].read_bytes(), ref['results'][seed])
    print(json.dumps(dict(scope=('Stock' if args.role=='stock' else 'LVT')+' four-wide BOOM RTL; Sv39 U-mode snapshot replay, not Linux boot or FPGA throughput.',
                          elf_sha256=ref['elf_sha256'], results=results), indent=2))
