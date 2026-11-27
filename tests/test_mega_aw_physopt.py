from pathlib import Path
from decimal import Decimal as D
import runpy
import unittest

m=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-mega-aw-physopt.py'))
aw=m['AW']; name=aw+'mem_0_size_reg[0]'; net=name+'_0[0]'
est=lambda w,t: f'INFO: [Physopt 32-619] Estimated Timing Summary | WNS={w} | TNS={t} |'
move=lambda n,c: f'INFO: [Physopt 32-663] Processed net {n}.  Re-placed instance {c}'
better=lambda n: f'INFO: [Physopt 32-735] Processed net {n}. Optimization improves timing on the net.'


class PlacedActions(unittest.TestCase):
    def test_named_aw_interval_and_terminal_duplicate(self):
        a=est('-8.300','-950.000'); b=est('-8.299','-951.000')
        first,last,c,cs,ns,bits=m['phase']('\n'.join([a,move(net,name),better(net),b,b])); self.assertEqual(cs,{name}); self.assertEqual(ns,{net});self.assertEqual(last[0]-first[0],D('.001'));self.assertEqual(bits['size'],1);self.assertEqual(c['AXI AW source queue']['wns_changes'],1)

    def test_mixed_interval_has_no_attributed_net_or_cell(self):
        lines=['INFO: [Physopt 32-702] Processed net X. Optimizations did not improve timing on the net.','INFO: [Physopt 32-81] Processed net Y. Replicated 10 times.',better('Y')]
        self.assertEqual(m['operations'](lines),('mixed',None,None))
        with self.assertRaises(ValueError): m['operations']([move(net,name),better('foreign')])

    def test_missing_action_and_truncation(self):
        a,b=est('-8.300','-950.000'),est('-8.299','-951.000')
        for sequence in [[a,b,b],[a,move(net,name),better(net),b],[a,move(net,name)]]:
            with self.assertRaises(ValueError):m['phase']('\n'.join(sequence))

    def test_exact_cell_not_replica_or_similar_prefix(self):
        hops=[{'driver':name+'_rep/Q','sink':name+'/CE','net':net},{'driver':'X/O','sink':name+'_extra/D','net':net+'_extra'}]
        self.assertEqual(m['exact_hits'](hops,{name},{net}),dict(exact_moved_cells=1,exact_processed_nets=1,aw_cells=1,aw_nets=1,aw_moved_input_pins={'CE':1}))

    def test_endpoint_clock_direction_and_hold_separate(self):
        header='destination_clock\tkind\tslack_ns\tlogic_levels\tfrom\tto\n'; rows=f'cpu\tmax\t-0.332\t3\tX/C\t{name}/D\ncpu\tmin\t0.021\t0\t{name}/C\tY/D\nui\tmax\t-0.233\t1\t{name}_rep/C\tZ/CE\n'; a=m['endpoints']((header+rows).encode(),{name}); self.assertEqual([r['aw_endpoint_matches'] for r in a],[[dict(rank=1,slack_ns='-0.332',pins={'to':'D'})],[dict(rank=1,slack_ns='0.021',pins={'from':'C'})],[]]);
        with self.assertRaises(ValueError):m['endpoints']((header+rows+rows).encode(),{name})
