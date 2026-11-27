from pathlib import Path
import runpy
import unittest

R = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-tl-wait.py'))
W = dict(mret_tick=100, user_ecall_trap_tick=320, fence_ticks=[115, 165, 215, 265, 315])
# First Get starts before the first hot PC. D.ready stalls are not intentionally injected wait time.
ROWS = [R['HEADER'], '20 0 4 6 0 0 21 21 28 8', '110 1 4 6 1 32 143 146 153 8',
        '164 1 0 6 2 0 165 168 168 1', '202 1 4 4 5 32 235 235 237 2', '310 1 4 3 1 32 343 345 345 1',
        '400 0 4 3 1 0 401 401 401 1', 'END 500 0 0 0']


class TlWaitReviewTests(unittest.TestCase):
    def parse(self, lines, window=W):
        return R['transactions']('\n'.join(lines)+'\n', window, 32)

    def reject_mutations(self, changes):
        for old, new in changes:
            with self.subTest(old=old, new=new):
                self.assertEqual(sum(row.count(old) for row in ROWS), 1)
                with self.assertRaises(ValueError):
                    self.parse([row.replace(old, new) for row in ROWS])

    def test_split_service_at_fences_and_exclude_ready_stalls(self):
        found = self.parse(ROWS)
        self.assertEqual(found['get_starts_by_round'], [0, 1, 0, 1])
        self.assertEqual(found['put_final_a_by_round'], [1, 0, 0, 0])
        self.assertEqual(found['user_gets_before_first_hot_pc'], 1)
        self.assertEqual(found['reads_outstanding_at_round_entry_before_new_a'], [1, 0, 1, 0])
        self.assertEqual(found['withheld_first_offer_ticks_overlapping_round'], [28, 12, 20, 4])

    def test_charge_wrong_privilege_or_write_or_uninjected_read(self):
        self.reject_mutations([('20 0 4', '20 1 4'), ('310 1 4', '310 0 4'), ('32 343', '0 311'),
                               ('2 0 165', '2 32 197')])

    def test_each_beat_is_not_a_new_request(self):
        self.reject_mutations([('32 143', '32 142'), ('153 8', '153 1'), ('146 153', '147 153'),
                               ('168 168 1', '168 175 8'), ('202 1 4', '168 1 4'),
                               ('END 500 0 0', 'END 500 0 450')])

    def test_reject_missing_late_transactions_or_trace_truncation(self):
        for rows in (ROWS[:-2]+ROWS[-1:], ROWS[:-1], ROWS[1:]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.parse(rows)

    def test_reject_unfinished_put_or_response_at_exit(self):
        for end in ('END 500 0 0 1', 'END 500 1 440 0'):
            with self.subTest(end=end), self.assertRaises(ValueError):
                self.parse(ROWS[:-1]+[end])

    def test_reject_nonmonotonic_rounds(self):
        for fence in (165, 164):
            with self.subTest(fence=fence), self.assertRaises(ValueError):
                self.parse(ROWS, dict(W, fence_ticks=[115, 165, fence, 265, 315]))
