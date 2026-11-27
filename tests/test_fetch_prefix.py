import copy
import runpy
import unittest
from pathlib import Path


M = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/prove-mega-fetch-prefix.py'))


def fixture():
    lines = []
    for j in range(32):
        sels = []
        for lane in reversed(range(8)):
            sel = '_GEN_'+str(9+33*lane+j)
            kw = 'if' if lane==7 else 'else if'
            sels.append(sel)
            lines += [f'    {kw} ({sel}) begin', f'      fb_uop_ram_{j}_inst <= io_enq_bits_exp_insts_{lane};',
                      f'      fb_uop_ram_{j}_debug_inst <= io_enq_bits_insts_{lane};', '    end']
        lines += ['    if ('+' | '.join(sels)+') begin', f'      fb_uop_ram_{j}_ftq_idx <= io_enq_bits_ftq_idx;', '    end']
    return '\n'.join(lines)+'\n'


class TestFetchPrefix(unittest.TestCase):
    def test_masked_store_preserves_control_and_other_payload(self):
        old = fixture(); new = M['masked'](old)
        self.assertEqual([s for s in old.splitlines() if '_inst <=' not in s or '_debug_inst' in s],
                         [s for s in new.splitlines() if '_inst <=' not in s or '_debug_inst' in s])
        rows = M['masked_body'](new, 2)
        self.assertEqual(len(rows),32)
        for j,line in enumerate(rows):
            sels = ['_GEN_'+str(9+33*i+j) for i in reversed(range(8))]
            self.assertIn('if ('+' | '.join(sels)+f') slot{j} <= ', line)
            for i,sel in zip(reversed(range(8)),sels):
                self.assertIn('({2{'+sel+'}} & io_enq_bits_exp_insts_'+str(i)+')', line)
        for broken in (old.replace('_GEN_240) begin','_GEN_241) begin',1), old.replace('io_enq_bits_exp_insts_0;', 'io_enq_bits_exp_insts_2;',1),
                       old.replace('    if (_GEN_240 |', '    if (_GEN_241 |',1), old+old):
            with self.assertRaises(ValueError):
                M['masked'](broken)
        with self.assertRaises(ValueError):
            M['masked_body'](new+'      fb_uop_ram_0_inst <= io_enq_bits_exp_insts_7;\n',2)

    def test_local_data_selector_does_not_weaken_ce(self):
        old=fixture(); global_rows=M['masked_body'](M['masked'](old),32)
        local_rows=M['masked_body'](M['masked'](old,local_select=True),32)
        for j,(glob,local) in enumerate(zip(global_rows,local_rows)):
            self.assertEqual(glob.split(' <= ')[0],local.split(' <= ')[0])
            data=local.split(' <= ')[1]
            self.assertNotIn('_GEN_',data)
            for i in range(8):
                ptr='tail' if i==0 else f'enq_idxs_{i}'
                self.assertIn(f'io_enq_bits_mask[{i}] & {ptr}[{j}]',data)

    def test_double_rotation_boundaries(self):
        text = 'wire [31:0] enq_idxs_2 = in_mask_1 ? _GEN_2 : enq_idxs_1;'
        alt = M['rewrite'](text,[2]); self.assertIn('{tail[29:0], tail[31:30]}',alt)
        for broken in (text+text, text.replace('_GEN_2','_GEN_3')):
            with self.assertRaises(ValueError):
                M['rewrite'](broken,[2])
        with self.assertRaises(ValueError):
            M['rewrite'](text,[1])

    def test_fdre_pins_not_top_output_aliases(self):
        widths = dict(clock=1, tail=32, head=8, maybe_full=1, io_enq_valid=1, io_enq_bits_mask=8,
                      **{f'io_enq_bits_exp_insts_{i}':2 for i in range(8)})
        ports = {}; cells = {}; n=10
        for name,w in widths.items():
            ports[name]=dict(direction='input',bits=list(range(n,n+w))); n+=w
        for j in range(32):
            ports[f'slot{j}']=dict(direction='output',bits=[n,n+1])
            for b in range(2):
                cells[f'q{n+b}']=dict(type='FDRE',connections=dict(C=ports['clock']['bits'],R=['0'],CE=ports['io_enq_valid']['bits'],
                                                                   Q=[n+b],D=[ports['io_enq_bits_exp_insts_0']['bits'][b]]))
            n+=2
        top=dict(ports=ports,cells=cells); good=M['profile'](top,[12,25]); self.assertEqual(good['fdre'],64)
        self.assertEqual(set(good['comb']['max_primitive_levels']),{'all_D','all_CE','slot11_bit25_D','slot12_bit12_D','slot23_bit25_D','slot24_bit25_D'})
        for mode in ('clock','reset','output_width','duplicate_Q','orphan_D','extra_output'):
            wrong=copy.deepcopy(top); po=wrong['ports']; ff=list(wrong['cells'].values()); w=ff[0]['connections']
            if mode=='clock':w['C']=po['io_enq_valid']['bits']
            if mode=='reset':w['R']=['1']
            if mode=='output_width':po['slot31']['bits'].append(10000)
            if mode=='duplicate_Q':w['Q']=ff[1]['connections']['Q']
            if mode=='orphan_D':w['D']=[10000]
            if mode=='extra_output':po['debug']=dict(direction='output',bits=w['Q'])
            with self.assertRaises(ValueError):
                M['profile'](wrong,[12,25])

    def test_solver_requires_one_unambiguous_result(self):
        yes='SAT proof finished - no model found: SUCCESS!'; no='SAT proof finished - model found: FAIL!'
        for ok in (False,True):
            M['decision'](yes if ok else no, ok)
            for invalid in ('',yes+no,(yes if ok else no)*2,no if ok else yes):
                with self.assertRaises(ValueError):
                    M['decision'](invalid,ok)
