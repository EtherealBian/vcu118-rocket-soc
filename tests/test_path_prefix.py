"""Vivado path decomposition regression with synthetic (not vendor) timing arcs."""
from pathlib import Path
import runpy
import unittest

api = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/review-path-prefix.py'))
base, src, clk = (api[n] for n in ('BASE', 'START', 'CLK'))


def report():
    sections = []
    for i in range(8):
        dst = base + 'core/int_issue_unit/slots_%d/p1_reg/D' % i
        cell = base + 'core/int_issue_unit/g%d' % i
        sections.append(f'''Slack (VIOLATED) : -1.000ns
  Source: {src}
  Destination: {dst}
  Path Group: {clk}
  Path Type: Setup (Max at Slow Process Corner)
  Requirement: 5.714ns (setup)
  Data Path Delay: 0.600ns (logic and nets)
  Logic Levels: 2 (LUT2=2)
    Source Clock Delay (SCD): 2.000ns
 FDRE r {src}
 FDRE (Prop_FDRE_C_Q) 0.100 2.100 r {src[:-1]}Q
 net (fo=1, unplaced) 0.100 2.200 shared_net
 r {base}lsu/common/I1
 LUT2 (Prop_LUT2_I1_O) 0.100 2.300 r {base}lsu/common/O
 net (fo=2, unplaced) 0.100 2.400 branch_net
 r {cell}/I0
 LUT2 (Prop_LUT2_I0_O) 0.100 2.500 r {cell}/O
 net (fo=1, unplaced) 0.100 2.600 output_net
 FDRE r {dst}
''')
    return '| Design State : Optimized\n' + ''.join(sections)


class Prefix(unittest.TestCase):
    def test_arrival_uses_launch_not_clock_origin(self):
        out = api['segment'](report())
        self.assertEqual((out['shared_combinational_cells_after_launch'], out['last_shared_output']), (1, 'lsu/common/O'))
        self.assertEqual(len(out['paths']), 8)
        for p in out['paths']:
            self.assertEqual((p['before_first_issue_input_ns'], p['from_first_issue_input_to_capture_ns'], p['levels_before_first_issue_input']), ('0.400','0.200',1))

    def test_mutated_reports_fail(self):
        text = report()
        for a,b in [('Optimized','Routed'),(clk,'other_clock'),('Setup (Max','Hold (Min'),
                    ('0.600ns','0.300ns'),('(SCD): 2.000','(SCD): 2.040'),('0.100 2.300','0.050 2.300'),
                    ('lsu/common/O','lsu/disconnected/O'),('lsu/common/I1','lsu/common/I0'),
                    ('slots_7','slots_6'),('Logic Levels: 2','Logic Levels: 3'),('Slack (VIOLATED)','Slack (MET)')]:
            with self.subTest(change=a), self.assertRaises(ValueError):
                api['segment'](text.replace(a,b))
        for bad in (text + 'Slack (MET) : 2.0ns\n',text.rsplit('Slack',1)[0],text.replace(' r '+base+'lsu/common/I1\n','')):
            with self.assertRaises(ValueError): api['segment'](bad)
