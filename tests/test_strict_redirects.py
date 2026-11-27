import json
from pathlib import Path
import runpy
import struct
import unittest

R = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-redirects.py'))
BEGIN, NEXT, END = (R['PROFILE'][k] for k in ('BEGIN', 'NEXT', 'END'))
A, B = 0x12000, 0x12008
PCS = [BEGIN, A, B, NEXT, NEXT, NEXT]
OPS = {pc: (b'0001', 2, 'c.nop') for pc in PCS}
OPS.update({A: (b'00001463', 4, 'bne'), B: (b'8082', 2, 'c.jr')})
W = dict(mret_tick=10, user_ecall_trap_tick=100, user_window_instructions=6,
         fence_ticks=[20, 55, 65, 75, 85], by_round_instructions=[3, 1, 1, 1])

def ticket(edge, slot):
    return edge*128+slot

T = [(20, ticket(14, 0)), (30, ticket(15, 5)), (47, ticket(37, 8)),
     (55, ticket(51, 15)), (65, ticket(60, 0)), (75, ticket(70, 1))]
E = [[30, T[1][1], A, B, 1, 1, 4], [39, ticket(34, 16), A, A+4, 1, 0, 4],
     [45, T[2][1], B, NEXT, 3, 1, 2]]

def parse(events=E, ticks=T, ops=OPS):
    return R['cohort'](b''.join(struct.pack('<I', p) for p in PCS),
                       b''.join(struct.pack('<II', *t) for t in ticks),
                       '\n'.join(' '.join(map(str, row)) for row in events), W, ops,
                       {'by_kind': {'conditional_branch': 1}})


class RedirectReviewTests(unittest.TestCase):
    def test_dynamic_join_not_static_pc(self):
        res = parse()
        self.assertEqual((res['matched'], res['not_joined_to_hot_retirement']), (2, 1))
        self.assertEqual(res['matched_by_round'], [2, 0, 0, 0])
        self.assertEqual(res['by_kind']['indirect'], {'matched': 1, 'retired': 1})
        self.assertEqual(res['intervals']['next_dispatch_minus_b2'], dict(n=2, min=6, p50=6, p95=7, max=7))

    def test_size_source_direction_target_kind(self):
        for col, new in [(2, A+2), (3, B+2), (4, 3), (5, 0), (6, 2)]:
            e = [list(x) for x in E]; e[0][col] = new
            with self.subTest(col=col), self.assertRaisesRegex(ValueError, 'mismatches'):
                parse(e)

    def test_bad_chronology_or_type(self):
        for col, new in [(0, 10), (0, 39), (1, T[2][1]), (4, 2), (6, 8)]:
            e = [list(x) for x in E]; e[0][col] = new
            with self.subTest(col=col), self.assertRaises(ValueError):
                parse(e)

    def test_reused_ticket_truncated_trace_or_wrong_commit_lane(self):
        for ticks in [T[:-1], [*T[:4], (65, T[0][1]), T[5]], [T[0], (20, T[1][1]), *T[2:]]]:
            with self.subTest(ticks=ticks), self.assertRaises(ValueError):
                parse(ticks=ticks)

    def test_final_hot_pc_uses_end_fence_as_successor(self):
        x = list(E)+[[72, T[-1][1], NEXT, END, 3, 1, 2]]
        row = parse(x, ops={**OPS, NEXT: (b'8082', 2, 'c.jr')})
        self.assertEqual(row['intervals']['next_commit_minus_b2']['n'], 3)
        self.assertEqual(row['intervals']['next_dispatch_minus_b2']['n'], 2)

    def test_elf_displacement_and_indirect_encodings(self):
        for w, destination in [(b'fe001ee3', A-4), (b'fc75', A-4), (b'c409', A+10)]:
            self.assertEqual(R['decode'](A, (w, len(w)//2, 'unused')), (1, destination))
        for w, size, kind in [(b'8082', 2, 3), (b'9082', 2, 3), (b'9002', 2, 0),
                              (b'00008067', 4, 3), (b'008000ef', 4, 0)]:
            self.assertEqual(R['decode'](A, (w, size, 'unused')), (kind, None))

    def test_shadow_predicts_before_training_and_carries_state_between_rounds(self):
        sh = R['DirectionShadow']()
        for rnd, taken in [(0, True), (0, True), (1, False), (2, False), (3, True)]:
            sh.update(A, taken, rnd)
        self.assertEqual(sh.wrong, {'bimodal': [1, 1, 1, 1], 'local4': [2, 0, 0, 1]})
        self.assertEqual(sh.hist[(A >> 1) & 255], 9)

    def test_public_summary_balances_against_independent_windows(self):
        docs = R['ROOT']/'docs'
        result = json.loads((docs/'perf-strict-redirects.json').read_bytes())
        lock = json.loads((docs/'perf-strict-user-lvt.json').read_bytes())
        reference = json.loads(R['REPLAY']['ORACLE'].read_bytes())
        self.assertEqual(result['elf_sha256'], reference['elf_sha256'])
        for seed, row in result['results'].items():
            matched = row['matched']
            self.assertEqual(row['all_user_b2'], matched+row['not_joined_to_hot_retirement'])
            self.assertEqual(matched, sum(row['matched_by_round']))
            self.assertEqual(matched, sum(row['matched_by_function'].values()))
            self.assertEqual(matched, sum(v['matched'] for v in row['by_kind'].values()))
            self.assertEqual(row['by_kind']['conditional']['retired'],
                             reference['results'][seed]['by_kind']['conditional_branch'])
            for k, v in lock['evidence'][seed].items():
                self.assertEqual(row['sha256'][k], v)
            for x in row['top10_by_matched']:
                self.assertEqual(x['matched'], sum(x['by_round']))
                self.assertLessEqual(x['matched_taken'], x['retired_taken'])
                self.assertLessEqual(x['matched']-x['matched_taken'], x['retired']-x['retired_taken'])
            for value in row['intervals'].values():
                self.assertLessEqual(value['min'], value['p50'])
                self.assertLessEqual(value['p50'], value['p95'])
                self.assertLessEqual(value['p95'], value['max'])
                self.assertEqual(value['n'], matched)  # neither pinned window ends in a matched branch

    def test_nearest_rank(self):
        self.assertEqual(R['spread']({-1: 1, 0: 18, 12: 1}), dict(n=20, min=-1, p50=0, p95=0, max=12))
