from copy import deepcopy
import json
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
G = runpy.run_path(str(ROOT/'scripts/test-mega-branch-cut.py'))


def tiny():
    ports, bits = {}, iter(range(2, 999))
    specs = [('clock',1), ('_rob_io_flush_valid',1)]
    for i in range(4):
        specs += list(zip(G['lane'](i)[0], (5,1,1)))
    for k,w in specs:
        ports[k] = dict(direction='input',bits=[next(bits) for _ in range(w)])
    ins = [b for k,p in ports.items() if k != 'clock' for b in p['bits']]
    obs = [next(bits) for _ in range(68)]
    ports['observed'] = dict(direction='output',bits=obs)
    cells = {}
    def cell(t, out, c):
        return dict(type=t, connections={n:[b] for n,b in c.items()},
                    port_directions={n:'output' if n == out else 'input' for n in c})
    for i,q in enumerate(obs):
        cells[str(i)] = cell('FDRE','Q',dict(C=ports['clock']['bits'][0], R='0',CE='1',D=ins[i%len(ins)],Q=q))
    o = next(bits)
    cells['lut'] = cell('LUT2','O',dict(I0=obs[0],I1=obs[1],O=o))
    obs[-1] = o
    return dict(ports=ports,cells=cells)


class Topology(unittest.TestCase):
    def test_depth_and_lsb_order(self):
        m = G['topology'](tiny())
        self.assertEqual(m['input_to_D_max'],dict.fromkeys(('tag','miss','valid','flush'),0))
        self.assertEqual(m['Q_to_resolve_levels'],{0:19,1:1})
        self.assertEqual(m['Q_to_mispredict_levels'],{0:20})

    def test_reject_wrong_edge_enable_reset(self):
        for pin,bit in [('C',3),('CE','0'),('R','1')]:
            with self.subTest(pin=pin), self.assertRaisesRegex(ValueError,'register clock'):
                m=tiny(); m['cells']['0']['connections'][pin]=[bit]; G['topology'](m)
        m=tiny(); m['cells']['0']['parameters']={'IS_C_INVERTED':'1'}
        with self.assertRaisesRegex(ValueError,'register clock'): G['topology'](m)

    def test_reject_bypass_feedback_cycle_and_duplicate_driver(self):
        base=tiny(); one=base['cells']['0']['connections']; lut=base['cells']['lut']['connections']
        for cell,pin,bits,err in [('lut','I0',one['D'],'bypasses register'),('0','D',lut['O'],'not an input cone'),
                                  ('lut','I0',lut['O'],'cycle'),('lut','O',one['Q'],'aliased driver')]:
            with self.subTest(fault=err), self.assertRaisesRegex(ValueError,err):
                m=deepcopy(base); m['cells'][cell]['connections'][pin]=bits; G['topology'](m)

    def test_closed_world(self):
        m=tiny(); m['cells']['lut']['type']='LATCH'
        with self.assertRaisesRegex(ValueError,'unexpected primitive'): G['topology'](m)
        m=tiny(); m['cells']['lut']['connections']['I1']=['x']
        with self.assertRaisesRegex(ValueError,'undriven'): G['topology'](m)
        for role in ('decode','qualified','banked'):
            with self.subTest(role=role), self.assertRaisesRegex(ValueError,'unique RTL edit site'):
                G['variant']('module unrelated; endmodule',role)


class Published(unittest.TestCase):
    def test_same_edge_controls_and_only_decode_kit(self):
        r=json.loads((ROOT/'docs/perf-mega175-branch-mask.json').read_bytes()); m=r['mapping']; proofs=r['proofs']
        self.assertEqual(r['stock_kit_sha256'],G['LOCK']); self.assertEqual(m['stock']['core_sha256'],G['UNIT'])
        self.assertEqual(set(m),set(G['ROLES']))
        self.assertEqual({k:v['result'] for k,v in proofs.items()},
                         {**{x+'-proof':'proved' for x in G['ROLES'][1:]},
                          **dict.fromkeys(('ignore-flush','wrong-lane','late-tag'),'counterexample')})
        self.assertEqual(r['decode_candidate']['changed'],{G['CORE']:m['decode']['core_sha256']})
        self.assertNotEqual(r['decode_candidate']['kit_sha256'],G['LOCK'])
        self.assertEqual([m[n]['cells']['FDRE'] for n in G['ROLES']], [28,108,188,80])
        self.assertEqual(m['decode']['Q_to_mispredict_levels'],{'2':20})
        self.assertEqual(m['stock']['Q_to_mispredict_levels'],{'3':16,'4':4})
        self.assertEqual(set(r['interface_lint']['modes']),{'SYNTHESIS','RANDOMIZE_REG_INIT'})


if __name__ == '__main__':
    unittest.main()
