from decimal import Decimal as D
from itertools import permutations
from pathlib import Path
import runpy
import unittest

m = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts'/'review-clock-domain-coverage.py'))
CPU,UI,TCK = m['CLOCKS']


class ClockScope(unittest.TestCase):
    def setUp(self):
        self.cross = [p for p in permutations(m['CLOCKS'],2) if CPU in p]
        self.inter = {p:('Ignored','Asynchronous Groups',17,None) for p in self.cross}
        self.cdc = {p:{('Critical','CDC-10','Asynch Clock Groups'):2} for p in self.cross}
        self.setup = {}; self.ignored = set(self.cross)
        for pair,cls,exc in [((CPU,CPU),'Clean','Timed'),((UI,'mmcm_clkout5'),'Ignored','Max Delay Datapath Only'),(('sys_clock','sys_clock'),'Clean','Partial False Path')]:
            self.inter[pair] = (cls,exc,30,D('-0.01')); self.setup[pair]=[(D('-0.014'),28)]
            if exc != 'Timed': self.ignored.add(pair)
        self.cdc['input port clock','sys_clock']={('Warning','CDC-8','False Path'):1}

    def join(self):
        return m['join'](self.inter,self.setup,self.ignored,self.cdc)

    def test_absence_is_not_a_clean_pair_and_counts_need_not_match(self):
        r=self.join(); self.assertEqual(len(r['group_directions']),6)
        self.assertEqual(sum('interaction_endpoints' not in x for x in r['group_directions']),2)
        self.assertEqual(r['cdc_only'],[dict(source='input port clock',destination='sys_clock',rows=1)])
        self.assertEqual(r['timed_controls'][0]['setup_wns_ns'],'-0.014')

    def test_cannot_lose_reported_direction(self):
        del self.inter[CPU,UI]
        with self.assertRaises(ValueError): self.join()

    def test_fabricated_timing_rejected(self):
        self.setup[UI,CPU]=[(D('0.003'),9)]
        with self.assertRaises(ValueError): self.join()

    def test_cannot_ignore_max_only(self):
        del self.setup[UI,'mmcm_clkout5']
        with self.assertRaises(ValueError): self.join()

    def test_partial_false_has_ignored_paths(self):
        self.ignored.remove(('sys_clock','sys_clock'))
        with self.assertRaises(ValueError): self.join()

    def test_wrong_exception_not_a_group(self):
        self.cdc[CPU,TCK]={('Warning','CDC-2','False Path'):1}
        with self.assertRaises(ValueError): self.join()

    def test_different_pair_slack(self):
        self.setup[CPU,CPU]=[(D('0.100'),28)]
        with self.assertRaises(ValueError): self.join()
