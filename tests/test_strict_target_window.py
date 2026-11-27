import runpy
import unittest
from collections import Counter
from pathlib import Path

M = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/count-target-user-window.py'))
W = M['W']; B,N,L = (W[k] for k in ('BEGIN','NEXT','LIST'))
OPS = {p:(b'0001',2,'c.nop') for p in (B,B+2,N,L,W['END'])}
TEXT = f'R 1 4\nR 2 4\nS 1 {B:x} {B+2:x}\nS 1 {N:x}\nS 4 {L:x}\nS 1 {B+2:x}\nDONE\n'


class FullWindow(unittest.TestCase):
    def parse(self, text=TEXT, mode='span'):
        return M['parse'](text,OPS,2,mode)

    def test_span_and_scalar_match(self):
        split = TEXT.replace(f'S 1 {B:x} {B+2:x}', f'S 1 {B:x}\nS 1 {B+2:x}')
        a,b = self.parse(),self.parse(split,'insn')
        self.assertEqual(M['compare']([a,b]), ([4,4],Counter({L:4,B+2:2,B:1,N:1})))

    def test_reject_partial_or_reordered_rounds(self):
        for t in [TEXT.replace('DONE\n',''),TEXT.replace('R 2','R 1'),TEXT.replace('R 1 4','R 1 5'),TEXT+'DONE\n']:
            with self.subTest(t=t), self.assertRaises(ValueError): self.parse(t)

    def test_reject_false_extent_and_wrong_counts(self):
        for t in [TEXT.replace(f'{B:x} {B+2:x}',f'{B:x} {L:x}'),TEXT.replace(f'{B+2:x}', 'ffffff'),
                  TEXT.replace(f'S 4 {L:x}',f'S 3 {L:x}\nS 1 {N:x}'),TEXT.replace(f'S 1 {B+2:x}\nDONE',f"S 1 {W['END']:x}\nDONE")]:
            with self.subTest(t=t), self.assertRaises(ValueError): self.parse(t)
        with self.assertRaisesRegex(ValueError,'one instruction'): self.parse(TEXT,'insn')

    def test_same_total_not_enough(self):
        r,h=self.parse()
        for changed in [([3,5],h),(r,Counter({L:4,B+2:1,B:2,N:1}))]:
            with self.assertRaisesRegex(ValueError,'disagree'): M['compare']([(r,h),changed])
