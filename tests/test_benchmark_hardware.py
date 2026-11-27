from hashlib import sha256
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

M=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/benchmark_hardware.py'))

class HardwareIdentityTests(unittest.TestCase):
    def test_require_independent_routed_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); bit='1'*64; boot={'bit_sha256':bit}
            line=b'clk_out1_harnessSysPLL  10.000   {0.000 5.000}  P,G,A  {harnessSysPLL/inst/mmcme4_adv_inst/CLKOUT0}\n'
            def make(clocks):
                files={'routed-clocks.rpt':clocks,'full-timing.rpt':b'timing'}
                for k,v in files.items():(root/k).write_bytes(v)
                sums={k:sha256(v).hexdigest() for k,v in files.items()}
                return dict(name='fixture',physical_harts=1,mhz=100,reports=sums),dict(**boot,route_and_constrained_timing_met=True,board_io_inventory_known=True,board_internal_coverage_met=True,reports_sha256=sums.copy())
            for data in (line,line+line,line.replace(b'10.000',b'20.000'),line.replace(b'CLKOUT0',b'CLKOUT1')):
                hw,cap=make(data)
                with patch.dict(M['HARDWARE'],{bit:hw}):
                    if data!=line:
                        with self.assertRaisesRegex(ValueError,'CPU clock'):M['verify'](boot,root,cap)
                        continue
                    self.assertEqual(M['verify'](boot,root,cap),hw)
                    with self.assertRaisesRegex(ValueError,'not bound'):M['verify'](boot,root,dict(cap,board_internal_coverage_met=False))
                    (root/'full-timing.rpt').write_bytes(b'another run')
                    with self.assertRaisesRegex(ValueError,'mismatch'):M['verify'](boot,root,cap)
            with self.assertRaisesRegex(ValueError,'no reviewed'):M['verify'](boot,root,cap)
