import copy
import importlib.util
from pathlib import Path
import sys
import unittest
S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
spec=importlib.util.spec_from_file_location('screen',S/'screen-core-windows.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


def sides():
    keys=('window.elf','window.bin','rocket_chiptop.cpp','sim','CANDIDATE.sha256')
    def side(base,cycles):
        group={'median_cycles_per_iteration':sorted(cycles)[1]/4,'median_retired_per_iteration':25,'median_ipc':100/sorted(cycles)[1],
            'samples':[{'sample':i,'cycles':n,'retired':100} for i,n in enumerate(cycles)]}
        return {'inputs':{k:(base if k in keys[-2:] else '')+k for k in keys},'performance_seed':group,'validation_seed':copy.deepcopy(group)}
    return side('a',[1000,800,800]),side('b',[1000,700,600])


class Budget(unittest.TestCase):
    def test_strict_cycle_win_is_not_budget_or_clock_pass(self):
        a,b=sides(); row=mod.screen(a,b,1,5000)['cycle_budget_screen']['groups']['performance_seed']
        self.assertEqual((row['matched_windows_with_lower_cycles'],row['windows_within_fixed_budget']),(2,2))
        self.assertEqual(row['break_even_candidate_to_reference_clock_ratio'],0.875)
        self.assertEqual(row['candidate_median_cycles_minus_budget'],-25)
    def test_reordered_or_different_elf_invalidates_screen(self):
        a,b=sides();b['validation_seed']['samples'][1]['sample']=2
        with self.assertRaises(ValueError):mod.screen(a,b)
        a,b=sides();b['inputs']['window.elf']='other'
        with self.assertRaises(ValueError):mod.screen(a,b)
        with self.assertRaises(ValueError):mod.screen(*sides(),target_mhz=0)
