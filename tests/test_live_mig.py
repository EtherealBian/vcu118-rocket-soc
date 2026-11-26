import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/'scripts/review-live-mig.py'
spec=importlib.util.spec_from_file_location('mig',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class LiveMigTest(unittest.TestCase):
    def test_missing_failed_and_disagreeing_stage(self):
        r='Overall Status: CAL PASS\nMicroBlaze Status: PASS\nDQS Gate Status: RUNNING\nMemory Interface Type: DDR4\nMemory Frequency (MHz): 800\nRanks: 1\nData Bytes: 8\nBits per Byte: 8\n'
        p='CALIBRATION_FAIL.STATUS string true FALSE\nCALIBRATION_FAIL.STAGE string true NONE\nCALIBRATION_FAIL.RANK string true NONE\nMICROBLAZE_START_UP string true PASS\nDQS_GATE_TRACKING string true RUNNING\n'
        for i in range(1,28):
            s='PASS' if i in (1,2,3,4,6,7,8,9,10,11,13,14) else 'SKIP'
            r+=f'{i} - Stage:  {s}\n'; p+=f'CAL_STATUS.RANK0.{i:02}_STAGE string true {s}\n'
        self.assertEqual(m.summarize(r,p)['rank0_stages_skipped'],15)
        for a,b in [(r.replace('CAL PASS','CAL FAIL'),p),(r,p.replace('FALSE','TRUE')),(r,p.replace('02_STAGE','01_STAGE')),(r.replace('27 - Stage:  SKIP','27 - Stage:  PASS'),p),(r,p.replace('01_STAGE string true PASS','01_STAGE string true SKIP'))]:
            with self.assertRaises(ValueError): m.summarize(a,b)
