import runpy
import struct
import unittest
from pathlib import Path

M = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-mega-timebase.py'))

class TimebaseReview(unittest.TestCase):
    sample = ('RTC intervals=1199 first=1100 last=1200100 period=1000\n'
              'GUEST ticks=256 lower=255950 upper=256050\n'
              'IRQ compare=1050 threshold=1050100 trap=1050107 disarm=1050145 mret=1050170\n')

    def test_bounds_and_frequency(self):
        result = M['examine'](self.sample, 175000000, 175000)
        self.assertEqual(result['guest_mcycle_bounds'], [255950, 256050])
        for ts in (174999, 175001, 0):
            with self.assertRaises(ValueError):
                M['examine'](self.sample, 175000000, ts)

    def test_uart_matches_cpu_brackets(self):
        r = M['examine'](self.sample,175000000,175000)
        good = b'UART5_READY v1\r\nUART5_HANDOFF\r\nT'+struct.pack('<II',255950,256050)+b'K'
        M['inspect_uart'](good,r)
        for bad in (good[:-1],good+b'!',good.replace(b'HANDOFF',b'IGNORED'),
                    good[:-9]+struct.pack('<II',255951,256050)+b'K'):
            with self.assertRaises(ValueError): M['inspect_uart'](bad,r)

    def test_invalid_cadence_brackets_and_interrupt(self):
        for a,b in [('1199','1198'),('256 lower','255 lower'),('255950','255744'),
                    ('256050','256256'),('256050','255999'),('1050 threshold','1051 threshold'),
                    ('1050107','1050099'),('1050145','1051100'),('1050170','1050130'),('IRQ','')]:
            with self.subTest(change=(a,b)), self.assertRaises(ValueError):
                M['examine'](self.sample.replace(a,b), 175000000, 175000)

    def test_clock_calls_from_executable_segment(self):
        elf=bytearray(0x5000); elf[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<H',elf,18,243); struct.pack_into('<Q',elf,32,64)
        struct.pack_into('<HH',elf,54,56,1)
        # Deliberately make file offset differ from low VA bits.
        struct.pack_into('<IIQQQQQQ',elf,64,1,5,256,0x10000,0,0x4f00,0x4f00,1)
        for pc, call in ((0x106ac,0x100040ef),(0x10f3a,0x073030ef)):
            struct.pack_into('<HI',elf,256+pc-0x10000-2,0x4501,call)
        struct.pack_into('<III',elf,256+0x47ac,0x50693,0x07100893,0x73)
        self.assertEqual(M['inspect_clock_calls'](elf)['syscall'],113)
        for pos in (68,256+0x6aa,256+0x6ac,256+0xf38,256+0xf3d,256+0x47ad,256+0x47b2,256+0x47b4):
            copy=bytearray(elf);copy[pos]^=1
            with self.subTest(byte=pos), self.assertRaises(ValueError):
                M['inspect_clock_calls'](copy)

if __name__ == '__main__':
    unittest.main()
