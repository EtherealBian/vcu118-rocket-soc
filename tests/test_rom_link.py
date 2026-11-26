import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
spec=importlib.util.spec_from_file_location('romlink',S/'review-clocked-rom-link.py'); link=importlib.util.module_from_spec(spec);spec.loader.exec_module(link)


class RomLink(unittest.TestCase):
    def test_evidence_requires_complete_correct_frame_and_wire_clock(self):
        self.assertEqual([link.selected_period(x) for x in (100,150,175)],[868,1302,1519])
        line='ROM_LINK_PASS mode=single bit_ticks=868 edge_intervals=9 frame_bytes=64 cycles=853412 quiet_bits=20\n'
        self.assertEqual(link.read_pass(line,'single',64,868)['cycles'],853412)
        for edited in [line.replace('single','quad'),line.replace('868','869'), line.replace('64','63'),line.replace('=9','=8'),line.replace('=20','=0'),line.replace('853412','100'),line+line]:
            with self.assertRaises(ValueError):link.read_pass(edited,'single',64,868)

    @unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget'),'needs device-tree tools')
    def test_unrelated_fixed_clock_does_not_satisfy_uart_contract(self):
        dts='''/dts-v1/; / { chosen {stdout-path="/serial";}; cpus {#address-cells=<1>;#size-cells=<0>;cpu@0 {reg=<0>;status="okay";};}; unused: c0 {clock-frequency=<175000000>;}; actual: c1 {clock-frequency=<100000000>;}; serial {compatible="sifive,uart0";clocks=<&actual>;}; };'''
        with tempfile.TemporaryDirectory() as tmp:
            kit=Path(tmp);(kit/'rom').mkdir();(kit/'rtl').mkdir(); (kit/'board.dts').write_text(dts)
            dtb=subprocess.check_output(['dtc','-q','-I','dts','-O','dtb',str(kit/'board.dts')]); (kit/'rom/sdboot.bin').write_bytes(b'probe123')
            raw=(b'probe123'+dtb).ljust(8192,b'\0');words=["64'h%016x"%int.from_bytes(raw[i:i+8],'little') for i in range(0,len(raw),8)]
            (kit/'rtl/TLROM.sv').write_text("wire [1023:0][63:0] _GEN = '{"+','.join(reversed(words))+"};")
            self.assertEqual(len(link.verify_kit_clock(kit,100,1)),64)
            for hz,harts in [(175,1),(100,4)]:
                with self.assertRaises(ValueError):link.verify_kit_clock(kit,hz,harts)
            (kit/'rom/sdboot.bin').write_bytes(b'probe124')
            with self.assertRaisesRegex(ValueError,'ROM/DT'):link.verify_kit_clock(kit,100,1)
