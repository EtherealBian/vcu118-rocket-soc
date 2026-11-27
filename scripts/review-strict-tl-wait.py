#!/usr/bin/env python3
"""Compare two external Get response delays on the same stock BOOM replay."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT/'scripts'
REPLAY = runpy.run_path(str(HERE/'review-strict-user-replay.py'))
BUILD = runpy.run_path(str(HERE/'test-strict-tl-wait.py'))
HEADER = BUILD['HEADER']


def transactions(text, window, extra):
    lines = text.splitlines()
    cuts = window['fence_ticks']
    start, stop = window['mret_tick'], window['user_ecall_trap_tick']
    if (extra not in (0, 32) or not lines or lines[0] != HEADER or len(cuts) != 5 or
            not start < cuts[0] < cuts[-1] <= stop or any(b <= a for a, b in zip(cuts, cuts[1:]))):
        raise ValueError('bad trace configuration')
    end = re.fullmatch(r'END (\d+) ([01]) (\d+) ([01])', lines[-1])
    if not end:
        raise ValueError('missing trace trailer')
    tick, live, pending, pending_put = map(int, end.groups())
    if tick <= stop or live or pending or pending_put:
        raise ValueError('unexpected final response or incomplete trace')
    gets, puts, waiting, carry_get = ([0]*4 for _ in range(4))
    prev = -1
    req_user = pre_get = post_get = 0
    late = early = False
    for line in lines[1:-1]:
        if not re.fullmatch(r'\d+(?: \d+){9}', line):
            raise ValueError('malformed TL event')
        a, u, op, sz, _src, delay, offer, first, last, beats = map(int, line.split())
        if (a <= prev or u != int(start < a <= stop) or op not in (0, 1, 4) or sz > 6 or
                delay != (extra if u and op == 4 else 0) or offer != a+1+delay or
                not offer <= first <= last < tick or beats != (1 << max(0, sz-3) if op == 4 else 1) or
                last-first+1 < beats or (beats == 1 and last != first)):
            raise ValueError('unexpected request, first-beat injection or D handshake')
        prev = last
        early |= last <= start
        late |= a > stop
        if u and op == 4:
            req_user += 1
            pre_get += a < cuts[0]
            post_get += a >= cuts[-1]
        for j, (lo, hi) in enumerate(zip(cuts, cuts[1:])):
            if lo <= a < hi:
                (gets if op == 4 else puts)[j] += 1
            if op == 4 and a < lo <= last:
                carry_get[j] += 1
            # [a+1, offer): exclude D.ready stalls and the data beats themselves.
            waiting[j] += max(0, min(hi, offer)-max(lo, a+1))
    if not early or not late or not req_user or sum(gets)+pre_get+post_get != req_user:
        raise ValueError('incomplete transactions around the window')
    return dict(complete_logged_transactions=len(lines)-2, all_user_gets=req_user,
                user_gets_before_first_hot_pc=pre_get, user_gets_at_or_after_end_pc=post_get,
                get_starts_by_round=gets, put_final_a_by_round=puts,
                reads_outstanding_at_round_entry_before_new_a=carry_get,
                withheld_first_offer_ticks_overlapping_round=waiting)


def digest(data):
    return sha256(data).hexdigest()


def review(out):
    lock = json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes())
    design = lock['designs']['stock']
    inputs = json.loads((out/'inputs.json').read_bytes())
    harness = BUILD['harness']((ROOT/'tests/mega_user_replay.cpp').read_text()).encode()
    if (out/'replay.cpp').read_bytes() != harness:
        raise ValueError('changed generated harness')
    want = {**lock['shared_inputs'], **{k: v for k, v in design.items() if k != 'model'},
            'strict_tl_wait.hpp': digest((ROOT/'tests/strict_tl_wait.hpp').read_bytes()),
            'replay.cpp': digest(harness), 'model': digest((out/'model').read_bytes())}
    if inputs != want:
        raise ValueError('wrong comparison runtime, archive, snapshots or harness')
    oracle = json.loads(REPLAY['ORACLE'].read_bytes())
    if oracle['elf_sha256'] != lock['elf_sha256']:
        raise ValueError('different guest executable in prior measurements')
    results = {}
    for seed in BUILD['SEEDS']:
        cases = {}
        for delay in (0, 32):
            d = out/str(delay)
            raw = {ext: (d/(seed+'.'+ext)).read_bytes() for ext in ('uart', 'pc', 'events', 'tl')}
            w = REPLAY['inspect'](raw['events'].decode(), raw['uart'], raw['pc'], oracle['results'][seed], include_widths=True)
            hashes = {k: digest(v) for k, v in raw.items()}
            stock, previous = lock['matched_windows'][seed], lock['evidence'][seed]
            if (hashes['pc'] != previous['pc'] or hashes['uart'] != previous['uart'] or
                    w['mret_tick'] != stock['mret_tick']):
                raise ValueError('different guest PC/state or boot timing')
            if not delay and (w != stock or hashes['events'] != previous['events']):
                raise ValueError('instrumentation changed the zero-delay reference')
            cases[str(delay)] = dict(cycles=w['user_window_cycles'], round_cycles=w['by_round_cycles'],
                                     mret_to_first_hot_pc_cycles=w['fence_ticks'][0]-w['mret_tick'],
                                     end_pc_to_trap_cycles=w['user_ecall_trap_tick']-w['fence_ticks'][-1],
                                     fence_ticks=w['fence_ticks'], tl=transactions(raw['tl'].decode('ascii'), w, delay),
                                     sha256=hashes)
        a, b = [cases[s]['round_cycles'] for s in ('0', '32')]
        results[seed] = dict(conditions=cases, delta_cycles=sum(b)-sum(a),
                             delta_cycles_by_round=[y-x for x, y in zip(a, b)])
    return dict(scope=('Fixed guest snapshots, one stock four-wide BOOM model. Accepted external Gets while CSR '
                       'privilege is U only. First D offer at A+1 or A+33, no change to later beats. Not MIG '
                       'calibration, DDR traffic prediction, full Linux, or board throughput.'),
                elf_sha256=oracle['elf_sha256'], inputs=inputs, results=results)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    print(json.dumps(review(p.parse_args().run), indent=2))
