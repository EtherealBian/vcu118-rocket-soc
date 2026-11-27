import hashlib
from pathlib import Path
import runpy
import struct
import unittest

M=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/profile-strict-user-window.py'))
CALL,BEGIN,END,CLOCK,LIST,NEXT=(M[k] for k in ('START_CALL','BEGIN','END','CLOCK','LIST','NEXT'))

class StrictUserWindowTests(unittest.TestCase):
    ops={pc:(b'0001',2,'c.nop') for pc in (CALL,BEGIN,END,CLOCK,LIST,NEXT,NEXT+2)}
    events=[CALL,CLOCK,BEGIN,LIST,LIST]+[NEXT,LIST,LIST]*3+[END,CLOCK]

    def result(self, seq):
        w=M['Window'](self.ops)
        for pc in seq: w.visit(pc)
        return w.finish()

    def test_bounds_and_order(self):
        p=self.result(self.events); hot=self.events[2:-2]
        self.assertEqual(p['by_round'],[3]*4); self.assertEqual(p['by_kind'],{'other_integer':12})
        self.assertEqual(p['ordered_pc_sha256'],hashlib.sha256(struct.pack('<12I',*hot)).hexdigest())

    def test_reject_wrong_clock_epoch_or_counts(self):
        for seq in [self.events[1:], self.events[:-1], self.events+[CLOCK], self.events[:2]+[CLOCK]+self.events[2:],
                    self.events[:2]+[END]+self.events[2:], self.events[:2]+[CALL]+self.events[2:], self.events[:-3]+self.events[-2:]]:
            with self.subTest(seq=seq),self.assertRaises(ValueError): self.result(seq)
        # Eight entries globally, but one round has one and another has three.
        bad=self.events.copy(); bad[4],bad[5]=bad[5],bad[4]
        with self.assertRaises(ValueError): self.result(bad)

    def test_wrong_trace_flags_and_opcodes(self):
        asm=b'0x00000000000106b0:  0001  nop\n'; ex=b'Trace 0: 0x1000 [0000000000000000/00000000000106b0/0x6000] \n'
        for part in ([asm.replace(b'0001  nop',b'0005  nop'),ex],[ex],[asm,ex.replace(b'/0x6000',b'/0x0000')],
                     [asm,asm,ex],[asm], [b'Trace 1:\n'], [asm,b'0x0000000000010af0:  0001  nop\n',ex]):
            with self.subTest(part=part),self.assertRaises(ValueError): M['trace'](part,self.ops,True)

    def test_single_step_rejects_multi_instruction_block(self):
        lines=[f'0x{pc:016x}:  0001  nop\n'.encode() for pc in (NEXT,NEXT+2)]
        lines+=[f'Trace 0: 0x123 [0000000000000000/{NEXT:016x}/0x6000] \n'.encode()]
        with self.assertRaisesRegex(ValueError,'block shape'): M['trace'](lines,self.ops,True)

    def test_no_unclassified_or_syscall_fallback(self):
        self.assertEqual(M['group']('c.ldsp'),'load'); self.assertEqual(M['group']('c.bnez'),'conditional_branch')
        with self.assertRaises(ValueError): M['group']('ecall')

if __name__=='__main__': unittest.main()
