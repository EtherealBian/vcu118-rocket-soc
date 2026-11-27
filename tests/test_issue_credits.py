"""Fail-closed source extraction and independently checked negative witness."""
import runpy
import unittest
from pathlib import Path

API=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/prove-issue-credits.py'))


def pair():
    leaves=['~_slots_%d_io_will_be_valid & ~issue_slots_%d_in_uop_valid'%(i,i) for i in range(4)]
    sum4=' + '.join("{2'h0, %s}" % x for x in leaves)
    old=['reg io_dis_uops_%d_ready_REG;'%i for i in range(4)]+['wire [2:0] num_available = '+sum4+';','always @(posedge clock) begin']
    new=['reg [2:0] vcuAvailPartials_0;', 'wire [2:0] num_available = vcuAvailPartials_0;', 'always @(posedge clock) begin','vcuAvailPartials_0 <= '+sum4+';', 'end']
    for i in range(4):old.append("io_dis_uops_%d_ready_REG <= num_available > 3'h%d;"%(i,i))
    old.append('end'); new.append("vcuAvailPartials_0 = _RANDOM[/*Zero width*/ 1'b0][2:0];")
    for i in range(4):old.append("io_dis_uops_%d_ready_REG = _RANDOM[/*Zero width*/ 1'b0][%d];"%(i,i))
    for i in range(4):
        old.append('assign io_dis_uops_%d_ready = io_dis_uops_%d_ready_REG;'%(i,i))
        new.append("assign io_dis_uops_%d_ready = num_available > 3'h%d;"%(i,i))
    return [('\n'.join(lines)+'\nassign unrelated = same;').encode() for lines in (old,new)]


class Credits(unittest.TestCase):
    def test_extraction_preserves_predicates_and_unrelated_logic(self):
        old,new=pair();(a,_,x),(b,c,y)=[API['extract'](v,4,i==1) for i,v in enumerate((old,new))]
        self.assertEqual(a,b);self.assertEqual(x,y);self.assertEqual(x,'assign unrelated = same;')
        self.assertIn("{2'h0, a[3]}",c)
        self.assertNotEqual(API['extract'](new.replace(b'= same;',b'= different;'),4,True)[2],x)

    def test_wrong_edge_guard_width_slot_and_threshold_source_rejected(self):
        new=pair()[1]
        for before,after in [(b'posedge',b'negedge'),(b'begin\n',b'begin\nif (enable) '),(b'reg [2:0]',b'reg [1:0]'),(b'issue_slots_3_in',b'issue_slots_0_in'),(b"num_available > 3'h2",b"other_ready > 3'h2")]:
            with self.subTest(before=before), self.assertRaises(ValueError):API['extract'](new.replace(before,after),4,True)

    def test_witness_checks_both_masks_at_second_step(self):
        log='    1 \\a 9 9 1001\n    2 \\changed 1 1 0001\n    2 \\orig 3 3 0011\n'
        self.assertEqual(API['counterexample'](log,4),dict(input_hex='9',reference_ready=3,mutant_ready=1))
        for bad in (log.replace('1001','0001'),log.replace('2 \\changed','1 \\changed'),log.replace('0011','1111')):
            with self.assertRaises(ValueError):API['counterexample'](bad,4)
