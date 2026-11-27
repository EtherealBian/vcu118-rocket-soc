"""Structural and fail-closed tests; exact generated RTL is checked by the proof tools."""
import copy
from pathlib import Path
import runpy
import unittest

CUT=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/map-mega-issue-cut.py'))
G=CUT['G']; M=G['M']


def grant_fixture():
    ports=[[f'_GEN_{p*40+i}' for i in range(40)] for p in range(4)]
    valid=[f'  assign io_iss_valids_{p} = '+ ' | '.join(gs[::-1])+';' for p,gs in enumerate(ports)]
    ack=[f'  assign issue_slots_{i}_grant = '+' | '.join(gs[i] for gs in reversed(ports))+';' for i in range(40)]
    return ports,'\n'.join(valid+ack)+'\n'


class IssueSelectors(unittest.TestCase):
    def test_bind_slot_to_grant_across_four_ports(self):
        ports,src=grant_fixture()
        self.assertEqual(M['grants'](src),ports)
        for bad in (src.replace('_GEN_155','_GEN_154'),src.replace('issue_slots_8_grant','issue_slots_9_grant'),
                    src.replace('_GEN_158 | _GEN_118','_GEN_118 | _GEN_158')):
            with self.assertRaises(ValueError): M['grants'](bad)

    def test_parse_real_chain_shapes(self):
        gs=grant_fixture()[0][0]; data=[f'_slots_{i}_io_uop_ctrl' for i in range(40)]
        terms=[f'{gs[i]} ? {data[i]}' for i in reversed(range(40))]; mux=lambda terms:' : '.join(terms)
        self.assertEqual(M['parse_field'](mux(terms+["4'h9"]),gs,'ctrl'),(data,4,9))
        self.assertEqual(M['parse_field'](mux(terms[:-1]+[gs[0]+' & '+data[0]]),gs,'ctrl'),(data,1,0))
        for bad in (terms[1:]+["4'h9"],terms+["4'h10"],terms+["65'h0"],
                    [terms[0].replace('_slots_39','_slots_38')]+terms[1:]+["4'h9"],terms[:-1]+[gs[0]+' & '+data[1]]):
            with self.assertRaises(ValueError):M['parse_field'](mux(bad),gs,'ctrl')

    def test_nonzero_idle_and_reject_truncation(self):
        mux=M['mask_mux']; self.assertIn("({4{~valid}} & 4'h9)",mux(['g0','g1'],['d0','d1'],4,9,'valid'))
        self.assertNotIn('~valid',mux(['g0'],['d0'],1,0,'valid'))
        for gs,ds,w,i in (([],[],1,0),(['a','b'],['x'],1,0),(['a'],['x'],0,0),(['a'],['x'],2,4)):
            with self.assertRaises(ValueError):mux(gs,ds,w,i,'valid')

    def test_inductive_miter_and_mutation(self):
        ports,_=grant_fixture(); base=G['parallel_select'](ports); broken=G['parallel_select'](ports,broken=True)
        delta=[(a,b) for a,b in zip(base.splitlines(),broken.splitlines()) if a!=b];self.assertEqual(len(delta),1)
        self.assertIn(' & ~(|vcu_req0[0:0])',delta[0][0]);self.assertNotIn('~',delta[0][1]);self.assertIn('vcu_req0[1]',delta[0][1])
        for p in range(4):
            assertion=G['miter']('','',[],p).split('assign ok = ')[1].split(';')[0]
            self.assertEqual(assertion,' || '.join([f'(a{k} != b{k})' for k in range(p)]+[f'(a{p} == b{p})']))
        with self.assertRaises(ValueError):G['parallel_select'](ports,3)


class IssueTopology(unittest.TestCase):
    @staticmethod
    def cell(a,y):return {'type':'INV','port_directions':{'I':'input','O':'output'},'connections':{'I':[a],'O':[y]}}

    def setUp(self):
        self.top={'ports':{'i':{'direction':'input','bits':[2]},'o':{'direction':'output','bits':[4,'1']}},
                  'cells':{'a':self.cell(2,3),'b':self.cell(3,4)}}

    def test_two_gates_and_direct_constant(self):
        self.assertEqual(CUT['topology'](self.top,{'o':2}),{'cells':{'INV':2},'total':2,'max_primitive_levels':{'o':2}})
        with self.assertRaises(ValueError): CUT['topology'](self.top,{'o':1})

    def test_invalid_even_outside_readout(self):
        for new in (self.cell(5,5), self.cell(50,5),self.cell(2,4),self.cell(2,2),self.cell('x',5),self.cell(2,'1')):
            with self.subTest(new=new):
                top=copy.deepcopy(self.top);top['cells']['unused']=new
                with self.assertRaises(ValueError):CUT['topology'](top,{'o':2})

    def test_topology_only_scalar_single_output_primitives(self):
        for mode in ('carry','vector','direction'):
            top=copy.deepcopy(self.top);cell=top['cells']['a']
            if mode=='carry':cell['type']='CARRY8'
            elif mode=='vector':cell['connections']['I'].append(2)
            else:cell['port_directions']['O']='inout'
            with self.assertRaises(ValueError):CUT['topology'](top,{'o':2})


class SourceSeal(unittest.TestCase):
    tools=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/derive-mega-issue-input.py'))

    def test_accept_one_modified_hdl_leaf_only(self):
        leaf=self.tools['LEAF'];old={leaf:M['UNIT'],'clock.xdc':'clock','sources.f':'list'};new={**old,leaf:'new'}
        self.tools['delta'](old,new)
        for bad in (old,{**new,'clock.xdc':'changed'},{**new,'extra.sv':'more'},{leaf:'new','sources.f':'list'}):
            with self.assertRaises(ValueError):self.tools['delta'](old,bad)
        with self.assertRaises(ValueError):self.tools['delta']({**old,leaf:'different'},new)

    def test_omitted_or_unexpected_proofs_fail(self):
        want={'all':'proved','mutant':'counterexample'};entries={k:{'result':v} for k,v in want.items()}
        self.tools['require_results'](entries,want)
        for wrong in ({'all':entries['all']},{**entries,'mutant':{'result':'proved'}},{**entries,'extra':{'result':'proved'}}):
            with self.assertRaises(ValueError):self.tools['require_results'](wrong,want)
