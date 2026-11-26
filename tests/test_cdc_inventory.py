import importlib.util
import unittest
from pathlib import Path


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/'scripts'/(name+'.py'))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


cdc=load('inventory-cdc'); fpga=load('review-fpga')


class CdcInventoryTests(unittest.TestCase):
    report='''CDC-99  Critical      1  Unexpected rule
Source Clock: A
Destination Clock: B
CDC Type: No Common Phase
  1  CDC-99  Critical  Unknown path  0  Asynch Clock Groups  a/Q  b/D
'''
    def test_new_critical_not_hidden(self):
        r=cdc.inventory(self.report); self.assertEqual(r['critical_families'],{'unclassified':1}); self.assertEqual(r['total_rows'],1)
        self.assertEqual((r['critical'][0]['source_clock'],r['critical'][0]['destination_clock']),('A','B'))

    def test_mismatched_summary_or_truncated_detail(self):
        for s in [self.report.replace('Critical      1','Critical      2'),self.report.replace('  1  CDC-99','  2  CDC-99'),self.report.replace('Source Clock: A','Source: A')]:
            with self.assertRaises(ValueError): cdc.inventory(s)

    def test_internal_coverage_nonzero_fails(self):
        self.assertTrue(fpga.board_coverage({'no_input_delay':5,'no_output_delay':6,'loops':0}))
        for k in ('unconstrained_internal_endpoints','no_clock','loops','unknown_rule'):
            self.assertFalse(fpga.board_coverage({k:1}))

    def test_disagreeing_check_timing_counts_rejected(self):
        with self.assertRaisesRegex(ValueError,'inconsistent'): fpga.counters('1. checking no_clock (0)\n1. checking no_clock (1)\n')


if __name__=='__main__':unittest.main()
