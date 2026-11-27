import copy
import json
from pathlib import Path
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
compare = runpy.run_path(str(ROOT / 'scripts/compare-early-way-rom-link.py'))['compare']


class EarlyWayRomPair(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / 'docs/perf175-early-way-rom-link.json').read_bytes())
        self.seals = self.record['distinct_inputs']['CANDIDATE.sha256']
        def sample(i):
            inputs = {k: v[i] for k, v in self.record['distinct_inputs'].items()}
            inputs.update(self.record['identical_inputs'])
            return dict(copy.deepcopy(self.record['identical_observations']), inputs=inputs)
        self.a, self.b = sample(0), sample(1)

    def test_pair_and_order(self):
        self.assertEqual(compare(self.a, self.b, self.seals), self.record)
        with self.assertRaisesRegex(ValueError, 'in that order'):
            compare(self.b, self.a, self.seals)

    def test_rejects_reused_archive_changed_probe_and_late_reply(self):
        for group, key, value in [('inputs', 'VChipTop__ALL.a', self.a['inputs']['VChipTop__ALL.a']),
                                  ('inputs', 'probe.elf', '0'*64),
                                  ('valid_frame', 'cycles', self.a['valid_frame']['cycles']+1)]:
            with self.subTest(key=key):
                edited = copy.deepcopy(self.b)
                edited[group][key] = value
                with self.assertRaises(ValueError):
                    compare(self.a, edited, self.seals)
