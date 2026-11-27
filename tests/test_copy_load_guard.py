from pathlib import Path
import json
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
G = runpy.run_path(str(ROOT/'scripts/prove-copy-load-guard.py'))


def skeleton():
    return 'unrelated;\n'+''.join(f'  wire copyload_hit_{i} = full_guard_{i};\n  wire [5:0] copyload_eff_{i} = copyload_hit_{i} ? src_{i} : base_{i};\n' for i in (1,2,3))+'keep;\n'


def section(num, text): return f'{num}. Executing SAT pass (solving SAT problems in the circuit).\n'+text


def fixed(name, value): return f"Final constraint equation: \\{name} = 1'{value}\n"


def shown(name, value): return f'  \\{name}    {value}    {value}    {value}\n'


class Guard(unittest.TestCase):
    def test_only_predicates_replaced(self):
        base=skeleton(); short=G['variant'](base)
        for i in (1,2,3):
            self.assertIn(f'io_dec_fire_{i}',G['equation'](short,i))
            self.assertEqual(G['mux'](short,i),G['mux'](base,i))
            short=short.replace(G['equation'](short,i),G['equation'](base,i))
        self.assertEqual(short,base)
        for bad in (base+base,base.replace('copyload_hit_2 =','missing_lane =')):
            with self.assertRaises(ValueError): G['variant'](bad)

    def test_wrong_signal_or_duplicate_connection_refused(self):
        body='.test_in   (net_x), .test_in_more (net_y)'; G['connection'](body,'test_in','net_x')
        for s in ('',body+body,body.replace('(net_x)','(net_0)')):
            with self.assertRaises(ValueError): G['connection'](s,'test_in','net_x')

    def test_every_guard_is_reachable_both_ways(self):
        log=section(1,"Final constraint equation: { } = { }\nFinal proof equation: \\equal = 1'1\n"+G['PASS']+'\n')
        for i in (1,2,3):
            name=f'full_hit_{i}'
            for b in (0,1): log+=section(2*i+b,fixed(name,b)+G['FOUND']+'\n'+shown(name,b))
        G['check_pair'](log)
        for bad in (log[:-12],log.replace('full_hit_2','full_hit_1'),log.replace('{ } = { }',"\\enable = 1'1"),log.replace(G['PASS'],'timeout')):
            with self.assertRaises(ValueError): G['check_pair'](bad)

    def test_wrong_counterexample_cannot_pass(self):
        vals={'equal':0,'full_hit_2':0,'bad_hit_2':1}
        log=fixed('equal',0)+G['FOUND']+'\n'+''.join(shown(k,v) for k,v in vals.items())
        G['witness'](log,'equal',0,vals)
        for bad in (log.replace('bad_hit_2','bad_hit_3'),log.replace(shown('bad_hit_2',1),shown('bad_hit_2',0)),log+shown('full_hit_2',0),log.replace('model found','no model found')):
            with self.assertRaises(ValueError): G['witness'](bad,'equal',0,vals)

    def test_recorded_results_consistent(self):
        load=lambda n:json.loads((ROOT/'docs'/n).read_bytes()); r=load('perf-copy-load-guard.json'); a=load('perf-copy-load-rename.json')
        self.assertEqual(r['full_leaf_sha256'],a['candidate_sha256']); self.assertNotEqual(r['short_leaf_sha256'],r['full_leaf_sha256'])
        self.assertEqual(r['equivalent_bits'],3*(1+6)); self.assertEqual(r['nonvacuity_witnesses'],6)
        self.assertEqual(r['shared_field_bits'],4*sum(G['W'].values())); self.assertEqual(len(G['W']),15)
        self.assertEqual(r['paired_rename'],{'cases':22,**{k:a[k] for k in ('simulator','bench_sha256','wiring_sha256')}})
        self.assertEqual({k:(v['lane'],v['full_hit'],v['broken_hit']) for k,v in r['negative_controls'].items()},
                         {'allow_copy_sfb':(1,0,1),'ignore_load_exception':(2,0,1),'disable_lane_3':(3,1,0)})
        for key in ('mapped','mapped_with_shared_fields'):
            pair=r[key]; self.assertEqual(set(pair),{'full','short'})
            for cut in pair.values():
                self.assertEqual(cut['mapped_vs_rtl'],'proved'); self.assertEqual(sum(cut['cells'].values()),cut['total'])
                self.assertEqual(set(cut['max_primitive_levels']),{f'cut_{n}_{i}' for n in ('hit','eff') for i in (1,2,3)})
                self.assertEqual(set(cut.get('tap_levels_max_across_lanes',{})),set(G['W']) if key=='mapped_with_shared_fields' else set())
        self.assertEqual(len({c['fixture_sha256'] for k in ('mapped','mapped_with_shared_fields') for c in r[k].values()}),4)
