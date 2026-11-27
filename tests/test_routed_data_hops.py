from pathlib import Path
import runpy
import unittest

M = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-mega-data-hops.py'))
SEP = '  -------------------------------------    -------------------\n'
D = dict(launch='start/C',capture='end/D',logic_levels=1,logic_ns='0.150',routing_ns='2.012',data_ns='2.162',slack_ns='-0.900')
BODY = '''    SLICE_X1Y1 FDRE (Prop_AFF_SLICEL_C_Q)
                   0.100 4.100 r start/Q
                 net (fo=35, routed) 2.000 6.100 word
    SLR Crossing[0->1]
    SLICE_X1Y250 f mux/I0
    SLICE_X1Y250 LUT4 (Prop_A6LUT_SLICEL_I0_O) 0.050 6.150 f mux/O
                 net (fo=1, routed) 0.012 6.162 choice
    SLICE_X1Y250 FDRE f end/D
'''

def path(body=BODY):
    return ('Slack (VIOLATED) : -0.900ns\n'+SEP+
            '                 net (fo=79911, routed) 3.999 4.000 clk\n    SLR Crossing[2->0]\n    SLICE_X1Y1 FDRE r start/C\n'+SEP+
            body+SEP+'    SLR Crossing[0->2]\n    data arrival time 6.162\n')

class RoutedDataHops(unittest.TestCase):
    def test_excludes_launch_and_capture_clock_trees(self):
        hops=M['decompose'](path(),D)
        self.assertEqual([(h['net'],h['driver'],h['sink'],h['slr_crossings']) for h in hops],
                         [('word','start/Q','mux/I0',[(0,1)]),('choice','mux/O','end/D',[])])
        self.assertEqual(hops[0]['driver_site'],'SLICE_X1Y1')
        self.assertEqual(M['decompose'](path().replace('FDRE r start/C','FDRE 0.000 4.000 r start/C'),D),hops)
        self.assertEqual(M['decompose'](path().replace(' Crossing[0->1]',' Crossing[0->2]'),D)[0]['slr_crossings'],[(0,2)])

    def test_shared_driver_to_different_sinks_is_not_a_shared_hop(self):
        secs=[path().replace('end/D',f'end{i}/D') for i in range(8)]
        ds=[dict(D,capture=f'end{i}/D') for i in range(8)]
        s=M['summarize'](''.join(secs),ds)
        self.assertEqual((s['distinct_data_hops'],s['repeated_hop_count']), (9,1))
        self.assertEqual(s['most_repeated'][0]['path_ranks'],tuple(range(1,9)))
        self.assertTrue(all(p['data_crossing_hops']==1 and p['crossing_hop_delay_sum_ns']=='2.000' for p in s['paths']))
        with self.assertRaises(ValueError):M['summarize'](''.join(secs[:-1]),ds)
        with self.assertRaises(ValueError):M['summarize'](''.join(secs[:-1]+[secs[-1].replace('fo=35','fo=31')]),ds)

    def test_rejects_stale_corrupt_or_unrouted_sections(self):
        for old,new in [('FDRE r start/C','FDRE r other/C'),('r start/Q','r other/Q'),('0.100 4.100','0.000 4.100'),('2.000 6.100','2.000 6.110'),('fo=35, routed','fo=35, estimated'),('fo=1, routed','fo=1, unrouted'),('SLR Crossing[0->1]','SLR Crossing[3->1]'),('SLR Crossing[0->1]','SLR Crossing[0->1]\n    SLR Crossing[0->2]'),('SLR Crossing[0->1]','SLR Crossing[0->0]'),('f mux/I0','f other/I0'),('SLICE_X1Y250 LUT4','SLICE_X2Y250 LUT4'),('f end/D','f extra/D')]:
            with self.subTest(old=old),self.assertRaises(ValueError):M['decompose'](path().replace(old,new),D)
        for key,val in [('logic_levels',5),('logic_ns','0.180'),('routing_ns','1.912'),('data_ns','2.362')]:
            with self.subTest(field=key),self.assertRaises(ValueError):M['decompose'](path(),dict(D,**{key:val}))
        with self.assertRaises(ValueError):M['decompose'](path(BODY[:BODY.index('SLICE_X1Y250 FDRE')]),D)
