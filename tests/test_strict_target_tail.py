import hashlib
from pathlib import Path
import runpy
import struct
import unittest

ROOT=Path(__file__).resolve().parents[1]
T=runpy.run_path(str(ROOT/'scripts/test-strict-target-tail.py'))
N,L=0x10af0,0x13b0c


class TargetTail(unittest.TestCase):
    def check(self, seq=None, **kw):
        pcs=([N,L,L]*8 if seq is None else seq)
        buf=struct.pack('<%dI'%len(pcs), *pcs)
        ref=dict(ordered_pc_sha256=hashlib.sha256(buf).hexdigest(),dynamic_instructions=len(pcs),by_round=[3]*8)
        ev=('MRET tick=100 epc=10af0 ret=1 satp=8 uart_bytes=21\n'
            'EXIT start=100 stop=140 cycles=40 u_arch_valid=28 mepc=147b4 cause=8 tval=0 lanes=12,28,0,0,0,\n'
            'WINDOW hot=24 pre=800000ec, post=10f3a,147ac,147b0, fences=103,108,110,112,118,121,128,133,137,\n')
        params=dict(events=ev,uart=T['REVIEW']['EPOCH'],trace=buf,ref=ref,target_tail=True);params.update(kw)
        return T['REVIEW']['inspect'](**params)

    def test_round_fence_zero_counted_once(self):
        self.assertEqual(self.check()['by_round_cycles'],[5,2,2,6,3,7,5,4])

    def test_reject_short_or_wrong_mode_and_pc(self):
        for args in [dict(target_tail=False),dict(seq=[0x106b0,L,L]+[N,L,L]*7),dict(seq=[L,N,L]+[N,L,L]*7),dict(seq=[N,L,L]*7+[N,L,N])]:
            with self.subTest(args=args),self.assertRaises(ValueError): self.check(**args)

    def test_generated_observer_not_architectural_mutation(self):
        src=(ROOT/'tests/mega_user_replay.cpp').read_text(); new=T['harness'](src)
        self.assertIn('epc == 0x10af0',new)
        self.assertIn('fence.size() == 9',new)
        with self.assertRaisesRegex(ValueError,'source hook'): T['harness'](new)

    def test_breakpoint_and_counter_guards(self):
        capture=runpy.run_path(str(ROOT/'scripts/capture-strict-user-guest.py'))['gdb_commands']
        default=capture(Path('/private'),1234);tail=capture(Path('/private'),1234,True)
        self.assertIn('hbreak *0x106b0',default);self.assertNotIn('condition 1',default)
        self.assertIn('hbreak *0x10af0\ncondition 1 $x14 == 23992 && $x25 == 24000',tail)
        self.assertIn('regs[25]==24000',tail);self.assertIn('23992 if tag',tail)

    def test_reject_repeated_pc_with_wrong_round_or_address_space(self):
        def snapshot(pc, count):
            regs = [0]*32
            regs[14], regs[25] = count, 24000
            return dict(pc=pc, priv=0, satp=8<<60, regs=regs)
        enter = snapshot(N, 23992); leave = snapshot(0x10f3a, 24000)
        T['check_fences'](enter, leave)
        for bad in (snapshot(N, 23991), dict(enter, priv=1), dict(enter, satp=(8<<60)+1)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                T['check_fences'](bad, leave)
