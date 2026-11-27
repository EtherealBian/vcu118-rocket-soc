import copy
import importlib.util
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('software_compare',HERE/'compare-window-software.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


class SoftwareComparison(unittest.TestCase):
    def setUp(self):
        self.a={'inputs':{k:k for k in ('sim','CANDIDATE.sha256','rocket_chiptop.cpp','sdboot.elf','window.elf','window.bin')}}
        for key in ('performance_seed','validation_seed'):
            self.a[key]={'samples':[dict(sample=i,cycles=100+i*4,retired=120) for i in range(3)]}
        self.b=copy.deepcopy(self.a)
        for key in ('window.elf','window.bin'):self.b['inputs'][key]+='-new'
        for key in ('performance_seed','validation_seed'):
            for r in self.b[key]['samples']:r.update(cycles=r['cycles']+8,retired=112)

    def test_fewer_retired_is_not_a_speedup(self):
        r=mod.compare(self.a,self.b)['comparison']['performance_seed']
        self.assertEqual(r['candidate_lower_cycles_count'],0)
        self.assertEqual((r['reference_median'],r['candidate_median']),(26,28))
        self.assertLess(r['median_retired_change_pct'],0)

    def test_rejects_changed_model_reused_binary_and_partial_group(self):
        for key in self.a['inputs']:
            b=copy.deepcopy(self.b);b['inputs'][key]=self.a['inputs'][key] if key.startswith('window.') else 'changed'
            with self.subTest(key=key),self.assertRaises(ValueError):mod.compare(self.a,b)
        self.b['performance_seed']['samples'].pop(1)
        with self.assertRaises(ValueError):mod.compare(self.a,self.b)
