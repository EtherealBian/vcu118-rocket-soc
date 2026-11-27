"""Gate tests for a two-reset ROM prefix. Constructed traces are not hardware evidence."""
from pathlib import Path
import runpy
import tempfile
import unittest

LIB = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/test-mega-recovery-linux.py'))


class RecoveryRomPrefix(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.d = Path(self.temp.name)
        self.traces = {'crc.uart':b'UART5_READY v1\r\nUART5_STOP CRC\r\n',
                       'crc.events':b'BAD_CRC_STOP tick=883890 quiet_bits=20\n',
                       'linux.uart':b'UART5_READY v1\r\nUART5_HANDOFF\r\n',
                       'linux.events':b'ROM_HANDOFF tick=838329 wire=24 backing_preloaded=5604352 edge_intervals=9 ticks_per_bit=1519\n'}
        for k,b in self.traces.items(): (self.d/k).write_bytes(b)

    def test_immutable_good_prefix_and_closed_fault_capture(self):
        scan=LIB['rom_prefix']; first=scan(self.d)
        for k in ('linux.uart','linux.events'):
            with (self.d/k).open('ab') as f: f.write(b'continuing trace\n')
        self.assertEqual(scan(self.d), first)
        with (self.d/'crc.uart').open('ab') as f: f.write(b'UART5_HANDOFF\r\n')
        with self.assertRaises(ValueError): scan(self.d)

    def test_truncation_wrong_clock_and_swapped_epochs(self):
        for k,b in self.traces.items():
            with self.subTest(k=k):
                (self.d/k).write_bytes(b[:-1]);
                with self.assertRaises(ValueError): LIB['rom_prefix'](self.d)
                (self.d/k).write_bytes(b)
        for k,v in [('linux.events',self.traces['linux.events'].replace(b'838329',b'838330')),
                    ('linux.uart',self.traces['crc.uart']),('crc.uart',self.traces['linux.uart'])]:
            with self.subTest(k=k):
                (self.d/k).write_bytes(v)
                with self.assertRaises(ValueError): LIB['rom_prefix'](self.d)
                (self.d/k).write_bytes(self.traces[k])
