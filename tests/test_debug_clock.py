import importlib.util
from pathlib import Path
import unittest

s=importlib.util.spec_from_file_location('clock_cmp',Path(__file__).resolve().parents[1]/'scripts/check-debug-clock.py')
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)


class DebugClockTests(unittest.TestCase):
    baseline='''EICG_wrapper gated_clock_debug_clock_gate (
 .in  (fabric),
 .out (gated)
);
wire debug_reset_sync = ~reset_n;
.debug_clock(gated),
.debug_reset(debug_reset_sync),
.debug_dmactiveAck(ack)
'''
    variant='''.debug_clock(fabric),
.debug_reset(~reset_n),
.debug_dmactiveAck(ack)
'''
    def test_gate_only(self):
        self.assertEqual(m.compare(self.baseline,self.variant),'fabric')

    def test_changed_reset_ack_or_clock_rejected(self):
        for a,b in [('~reset_n','reset_n'),('fabric','alternate'),('ack)','other)'),('.debug_clock(fabric),','')]:
            with self.subTest(), self.assertRaises(ValueError): m.compare(self.baseline,self.variant.replace(a,b))
