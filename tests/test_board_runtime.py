"""A terminal echo, stale nonce, or missing timer progress cannot qualify as a board workload."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('runtime_profile', Path(__file__).resolve().parents[1]/'scripts/review-linux-profile.py')
profile=importlib.util.module_from_spec(spec); spec.loader.exec_module(profile)
NONCE='14cafe1234cafe'
LOG='''echo LIVE_$((19+23))_TOKEN
LIVE_42_TOKEN
# echo BEGIN_$((20+22))_TOKEN; ...
BEGIN_42_TOKEN
NAME
Linux 6.6.65 riscv64
CPU
processor : 0
hart : 0
isa : rv64imafdc_zicntr_zicsr
mmu : sv39
uarch : sifive,rocket0

MEM
MemTotal:        2043000 kB
UP1
12.00 9.98
IRQ1
 1:    33 RISC-V INTC 5 Edge riscv-timer
LOAD
SOC_CHECK_PASS bytes=16777216 passes=6 elapsed_s=15
STATUS_0
UP2
27.67 10.00
IRQ2
 1:    98 RISC-V INTC 5 Edge riscv-timer
END_42_TOKEN
# '''.replace('TOKEN',NONCE).replace('\n','\r\n').encode()

class RuntimeProfileTests(unittest.TestCase):
    def test_good(self):
        r=profile.parse(LOG,NONCE,15676);self.assertEqual((r['write_read_passes'],r['timer_interrupt_delta'],r['uptime_window_seconds']),(6,65,'15.67'))
    def test_rejections(self):
        for old,new in [(b'LIVE_42_',b'echo LIVE_42_'),(b'98 RISC-V',b'33 RISC-V'),(b'2043000',b'123000'),(b'27.67',b'12.67'),(b'STATUS_0',b'STATUS_1'),(b'\r\nLOAD\r\n',b'\r\nLOAD\r\nLOAD\r\n'),(b'sv39',b'sv48'),(b'rv64imafdc',b'rv64imac'),(b'END_42_',b'END_$((20+22))_')]:
            with self.subTest(old=old),self.assertRaises(ValueError):profile.parse(LOG.replace(old,new),NONCE)
        with self.assertRaises(ValueError):profile.parse(LOG,'9'*14)
        with self.assertRaises(ValueError):profile.parse(LOG,NONCE,10800)
