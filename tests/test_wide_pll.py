import importlib.util
from pathlib import Path
import unittest

script=Path(__file__).resolve().parents[1]/'scripts/promote-wide-model.py'
spec=importlib.util.spec_from_file_location('promote',script); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class ClockContract(unittest.TestCase):
    reference=b'CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {100.0}\n$freq < 99.0 || $freq > 101.0\nrange 99.0-101.0\n'
    def test_frequency_change_is_exact(self):
        self.assertEqual(mod.pll_expected(self.reference,100),self.reference)
        self.assertEqual(mod.pll_expected(self.reference,175),b'CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {175.0}\n$freq < 173.25 || $freq > 176.75\nrange 173.25-176.75\n')
    def test_missing_duplicated_or_unapproved_clock_rejected(self):
        for ref,mhz in [(self.reference,150),(self.reference*2,175),(self.reference.replace(b'101.0',b'110.0'),175)]:
            with self.assertRaises(ValueError): mod.pll_expected(ref,mhz)
