"""Negative controls for the paired-window and high-clock transplant evidence."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
R = runpy.run_path(str(ROOT/'scripts/review-early-way-windows.py'))
D = runpy.run_path(str(ROOT/'scripts/derive-early-way175.py'))


class EarlyWayExperiments(unittest.TestCase):
    def setUp(self):
        def doc(name): return json.loads((ROOT/'docs'/name).read_bytes())
        self.originals = {key:doc('perf-wide-'+key+'.json')['candidate'] for key in ('o2','o3')}
        self.summary = doc('perf-early-way-windows.json'); self.seals = doc('perf-early-way-cone.json')['kit_seals']
        self.pairs = {k:[copy.deepcopy(v),copy.deepcopy(v)] for k,v in self.originals.items()}
        for _,new in self.pairs.values():
            new['inputs']['sim'] = self.summary['sim_sha256_stock_early'][1]
            new['inputs']['CANDIDATE.sha256'] = self.seals[1]

    def check(self): return R['summarize'](self.pairs,self.originals,self.seals)

    def test_published_rows_and_totals(self):
        self.assertEqual(self.check(),self.summary)
        self.assertNotEqual(self.summary['profiles']['o2']['performance_seed']['identical_samples'][0]['retired'],
                            self.summary['profiles']['o3']['performance_seed']['identical_samples'][0]['retired'])

    def test_nonmedian_cycle_and_retire_changes_fail(self):
        for key in ('cycles','retired'):
            row = self.pairs['o2'][1]['performance_seed']['samples'][0]; row[key] += 1
            with self.assertRaises(ValueError): self.check()
            row[key] -= 1

    def test_missing_or_duplicate_sample_fails(self):
        rows = self.pairs['o3'][1]['validation_seed']['samples']; last = rows.pop()
        with self.assertRaises(ValueError): self.check()
        rows.append(rows[1])
        with self.assertRaises(ValueError): self.check()
        rows[-1] = last

    def test_swapped_kit_duplicate_payload_and_archive_fail(self):
        self.pairs['o2'].reverse()
        with self.assertRaises(ValueError): self.check()
        self.pairs['o2'].reverse(); self.pairs['o3'] = self.pairs['o2']
        with self.assertRaises(ValueError): self.check()
        self.originals['o3'] = self.originals['o2']
        with self.assertRaises(ValueError): self.check()

    def test_run_counters_and_harness_are_not_optional(self):
        new = self.pairs['o2'][1]
        for key in R['TOTALS']:
            new[key] += 1
            with self.assertRaises(ValueError): self.check()
            new[key] -= 1
        for key in ('sdboot.elf','rocket_chiptop.cpp','sim'):
            saved = new['inputs'][key]; new['inputs'][key]='0'*64
            with self.assertRaises(ValueError): self.check()
            new['inputs'][key]=saved

    def test_transplant_only_one_qualified_file_without_aliasing(self):
        mod = D['MODULE']; stock = {mod:b'old','rtl/TLROM.sv':b'175'}; dig = lambda s:sha256(s).hexdigest()
        result = D['transplant'](stock,b'new',dig(b'old'),dig(b'new'))
        self.assertEqual(stock[mod],b'old'); self.assertEqual(result,{mod:b'new','rtl/TLROM.sv':b'175'})
        for orig,changed in ((b'bad',b'new'),(b'old',b'bad'),(b'old',b'old')):
            with self.assertRaises(ValueError): D['transplant'](stock,b'new',dig(orig),dig(changed))
