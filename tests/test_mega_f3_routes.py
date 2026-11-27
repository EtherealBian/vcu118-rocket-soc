"""Offline coverage and same-endpoint accounting for the registered F3 reviewer."""
import csv
import json
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = runpy.run_path(str(ROOT / 'scripts/review-mega-f3-routes.py'))
PROOF = json.loads((ROOT / 'docs/perf-mega175-f3-registered.json').read_bytes())


class F3PairTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'paths.tsv'
        self.rows = []
        for group, delay in [('all', 'max'), ('all', 'min'), *((str(l), 'max') for l in range(8))]:
            for bit in range(82):
                required = group == 'all' or bit in PROOF['predicted_lane_to_capture_dependent_bits'][int(group)]
                data = ['path', 0 if group == 'all' else int(group), '1.001', '1.0', 3] if required else ['no_path'] + ['-'] * 4
                self.rows.append([group, delay, bit, int(required), *data])

    def read(self):
        with self.path.open('w', newline='') as f:
            writer = csv.writer(f, delimiter='\t'); writer.writerow(R['FIELDS']); writer.writerows(self.rows)
        return R['endpoints'](self.path, PROOF)

    def test_direction_pair_delta_at_fixed_endpoints(self):
        stock = self.read(); candidate = stock.copy()
        key = ('7', 'max', 68); candidate[key] = dict(stock[key], slack_ns=1.0)
        counts = R['compare'](PROOF, stock, candidate)['all_required']
        self.assertEqual([counts[k] for k in ('improved', 'worsened', 'equal')], [0, 1, 356])
        self.assertEqual(counts['smallest_delta'], dict(delta_ps=-1, lane=7, capture_bit=68))

    def test_missing_capture_is_rejected(self):
        self.rows.pop(81)
        with self.assertRaisesRegex(ValueError, '820'):
            self.read()

    def test_incorrect_sat_flag_is_rejected(self):
        row = next(r for r in self.rows if r[0] == '7' and r[2] == 68); row[3] = 0
        with self.assertRaisesRegex(ValueError, 'incorrect dependence'):
            self.read()

    def test_duplicate_cannot_replace_a_missing_capture(self):
        self.rows[-1] = self.rows[-2]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.read()

    def test_absent_required_path_is_rejected(self):
        row = next(r for r in self.rows if r[0] == '7' and r[2] == 68); row[4:] = ['no_path'] + ['-'] * 4
        with self.assertRaisesRegex(ValueError, 'missing required path'):
            self.read()
