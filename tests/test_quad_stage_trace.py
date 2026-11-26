import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from quad_stage_trace import analyze

class Trace(unittest.TestCase):
    @staticmethod
    def rows():
        items=[(10+i*12+s,h,s,0x80+(i%8)*4) for h in range(4) for i in range(256) for s in range(9)]
        return ['TRACE %d %d %d %d'%r for r in sorted(items)]
    def test_nine_cycle_witness_all_harts(self):
        result=analyze(self.rows(),128,160);self.assertEqual([r['contiguous_witnesses'] for r in result['harts']],[256]*4)
    def test_missing_instruction_stage_or_hart_fails(self):
        good=self.rows()
        for bad in (good[:-1], [x for x in good if ' 0 3 ' not in x], [x for x in good if x.split()[2]!='2'],good+[good[0]]):
            with self.assertRaises(ValueError):analyze(bad,128,160)

    def test_halfword_before_issue_requires_positive_kill_and_no_execute(self):
        tail=['TRACE 9000 1 4 130','TRACE 9001 1 5 130 issue_killed']
        self.assertEqual(analyze(self.rows()+tail,128,160)['halfword_issue_kills'],1)
        for extra in [tail[:1],tail[1:], [tail[0],tail[1].replace(' issue_killed','')],
                      tail+['TRACE 9002 1 6 128'], ['TRACE 9000 1 8 130'],
                      [tail[0],tail[1].replace('130','134')]]:
            with self.assertRaises(ValueError):analyze(self.rows()+extra,128,160)
