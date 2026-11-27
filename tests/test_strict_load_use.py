import runpy
from pathlib import Path
import struct
import unittest

R=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-load-use.py'))


class OperandTimeline(unittest.TestCase):
    def setUp(self):
        self.br=R['BR']; self.neg=(1<<64)-2
        self.loads=[(15,0,62,self.neg),(18,1,41,7)]
        self.exe=(20,2,self.neg,7); self.b1=(21,2,self.br,0,1)
        self.rd=(22,self.br,self.br+4,1,0,4)

    def check(self,**overrides):
        a=dict(loads=self.loads,exe=self.exe,b1=self.b1,retire=25,successor=self.br+4,rd=self.rd)
        return R['sample'](**dict(a,**overrides))

    def test_signed_forward_values(self):
        self.assertEqual(self.check(),18)
        self.assertEqual(self.check(b1=(21,2,self.br,0,0),rd=None),18)

    def test_unsigned_halfword_and_changed_value(self):
        for bad,actual in [(self.neg^1,self.neg),(65534,65534)]:
            with self.assertRaisesRegex(ValueError,'sign-extended ALU'):
                self.check(loads=[(15,0,62,bad),self.loads[1]],exe=(20,2,actual,7))

    def test_independent_successor_lane_and_b2(self):
        for bad in [dict(successor=0x13f3a),dict(b1=(21,3,self.br,0,1)),dict(b1=(22,2,self.br,0,1)),
                    dict(rd=None),dict(rd=(22,self.br,self.br+4,1,1,4))]:
            with self.assertRaisesRegex(ValueError,'successor mismatch'): self.check(**bad)

    def test_duplicate_and_late_allocation(self):
        line='L 21 259 0 3 0'
        with self.assertRaises(ValueError): R['events'](line+'\n'+line)
        with self.assertRaises(ValueError): R['events']('L 2 259 0 3 0')

    def test_selection_keeps_only_wanted_tickets(self):
        n=R['CAP']['selection'](dict(pc=struct.pack('<III',R['LEFT'],88,self.br),tickets=struct.pack('<IIIIII',20,111,20,112,21,113)))
        self.assertEqual(n,f'111 {R["LEFT"]}\n113 {self.br}\n')
