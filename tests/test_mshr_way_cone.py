"""Cone checker tests use small Verilator-shaped fixtures, not a generated BOOM run."""
from copy import deepcopy
import io
from pathlib import Path
import runpy
import unittest
import xml.etree.ElementTree as ET


API = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/check-mshr-way-cone.py'))


def expr(tag, w, *children, **attrs):
    n = ET.Element(tag, dtype_id=str(w), **attrs); n.extend(children); return n


def ref(name,w): return expr('varref',w,name=name)


def fixture(corrected, mutate=None):
    root = ET.Element('root'); table=ET.SubElement(root,'typetable')
    for width in (1,3,8):ET.SubElement(table,'basicdtype',id=str(width),name='logic',left=str(width-1),right='0')
    m=ET.SubElement(root,'module',name=API['MODULE']); a=ET.SubElement(m,'always')
    e=ET.SubElement(ET.SubElement(a,'sentree'),'senitem',edgeType='POS');e.append(ref('clock',1)); b=ET.SubElement(a,'begin')
    def reg(name,rhs,w): b.append(expr('assigndly',w,rhs,ref(name,w)))
    def mux(mask,index):
        return expr('cond',8,expr('redor',1,deepcopy(mask)),mask,expr('shiftl',8,expr('const',8,name="8'h1"),index))
    port=ET.SubElement(ET.SubElement(m,'instance',name='mshrs',defName='BoomMSHRFile'),'port',name=API['PIN'],direction='in')
    if not corrected:
        reg(API['TAG'],ref('s1mask',8),8);reg(API['REPL'],ref('s1index',3),3)
        port.append(mux(ref(API['TAG'],8),ref(API['REPL'],3)))
    else:
        m.append(expr('contassign',8,ref('s1mask',8),ref('alias',8)))
        reg('way',mux(ref('alias',8),ref('s1index',3)),8);port.append(ref('way',8))
    if mutate: mutate(m,a,b,e,port)
    return API['Cone'](io.BytesIO(ET.tostring(root)))


class Way(unittest.TestCase):
    def test_full_mask_without_one_hot_assumption(self):
        r=API['check_cones'](fixture(False),fixture(True))
        self.assertEqual((r['single_edge_vectors'],r['multi_hot_vectors']),(2048,1976))
        for key in ('high_bit_dropped_witness','extra_register_witness'):
            self.assertNotEqual(r[key]['reference'],r[key]['mutant'])

    def test_wrong_bit_function_rejected(self):
        def broken(m,a,b,e,p): b[0][0][2][0].set('name',"8'h2")
        with self.assertRaisesRegex(ValueError,'mismatches'):API['check_cones'](fixture(False),fixture(True,broken))

    def test_wrong_edge_guard_alias_or_second_flop_rejected(self):
        def guard(m,a,b,e,p):
            d=b[0];b.remove(d);ET.SubElement(b,'if').append(d)
        def second(m,a,b,e,p):
            b.append(expr('assigndly',8,ref('way',8),ref('late',8)));p[0].set('name','late')
        def other(m,a,b,e,p): m.find('contassign')[0].set('name','wrong_input')
        for fn in (guard,second,other,lambda m,a,b,e,p:e.set('edgeType','NEG')):
            with self.subTest(fn=fn), self.assertRaises(ValueError):API['check_cones'](fixture(False),fixture(True,fn))

    def test_zero_extension_only_above_the_replacement_index(self):
        wire, match = API['var'], API['match_shift_index']
        a,b,c = [wire(k,1) for k in 'abc']
        def cat(a,b):return ('concat',a[1]+b[1],(),(a,b))
        def ext(a):return ('extend',6,(('width','6'),('widthminv','1')),(a,))
        orig=cat(a,cat(b,c)); left=('const',8,(('name',"8'h1"),),())
        shift=lambda k:('shiftl',8,(),(left,k))
        self.assertEqual(match(shift(cat(ext(a),cat(b,c))),orig),shift(wire('INDEX',3)))
        for wrong in (cat(ext(c),cat(b,a)),cat(a,cat(ext(b),c)),cat(a,b)):
            with self.assertRaisesRegex(ValueError,'index'):match(shift(wrong),orig)

    def test_equal_offsets_fold_but_signed_negative_or_invalid_range_rejected(self):
        cone=fixture(False); v=ref('addr',8)
        a=expr('sel',3,v,expr('const',3,name="3'h2"),expr('const',3,name="3'h3"))
        b=deepcopy(a);b[1].set('dtype_id','8');b[1].set('name',"8'h2")
        self.assertEqual(cone.ast(a),cone.ast(b))
        b[1].set('name',"8'h6")
        with self.assertRaisesRegex(ValueError,'out-of-range'):cone.ast(b)
        cone.dt['8'].set('signed','true'); b[1].set('name',"8'hfe"); b[0].set('dtype_id','3')
        with self.assertRaisesRegex(ValueError,'negative'):cone.ast(b)
