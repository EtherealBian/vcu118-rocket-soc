import copy
import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = runpy.run_path(str(ROOT / 'scripts' / 'prove-l2-directory-hit-tag.py'))


class TestDirectoryTag(unittest.TestCase):
    def test_only_hit_branch_rewritten(self):
        terms = ["(_hits_T_%d ? _cc_dir_RW0_rdata[%d:%d] : 16'h0)" %
                 (6 + 7*w, 20*w+15, 20*w) for w in range(8)]
        prefix = 'assign io_result_bits_tag = (|hits) ? '
        miss = ' : _view__T_69 ? _write_q_io_deq_bits_data_tag : victim_bits;'
        stock = prefix + ' | '.join(terms) + miss
        alt = MODEL['candidate'](stock)
        self.assertEqual(alt, prefix + 'tag' + miss)
        for bad in (stock + stock, stock.replace(terms[4], terms[3]), stock.replace(' | ' + terms[-1], '')):
            with self.assertRaises(ValueError):
                MODEL['candidate'](bad)
        for parallel in (False, True):
            new = MODEL['partition'](alt + '\nassign next = independent;', parallel)
            self.assertEqual(new.count('victim_bits'), 1)
            self.assertTrue(new.endswith('\nassign next = independent;'))
            with self.assertRaises(ValueError):
                MODEL['partition'](alt.replace('_view__T_69', 'changed'), parallel)

    def test_muxcy_shape_and_opt_in(self):
        dirs = dict(CI='input', DI='input', S='input', O='output')
        pins = dict(CI=[2], DI=[3], S=[4], O=[5])
        ports = dict(i=dict(direction='input',bits=[2,3,4]),o=dict(direction='output',bits=[5]))
        top = dict(ports=ports,cells={'c':dict(type='MUXCY', connections=pins, port_directions=dirs)})
        f = MODEL['TOPOLOGY']
        with self.assertRaises(ValueError):
            f(top, {'o':1})
        self.assertEqual(f(top, {'o':1}, allow_muxcy=True)['max_primitive_levels'], {'o':1})
        for broken in ('missing_connection','missing_interface','wrong_width'):
            bad = copy.deepcopy(top); cell = bad['cells']['c']
            if broken == 'wrong_width':
                cell['connections']['CI'].append(3)
            else:
                del cell['connections']['S']
                if broken == 'missing_interface':
                    del cell['port_directions']['S']
            with self.assertRaises(ValueError):
                f(bad, {'o':1}, allow_muxcy=True)
