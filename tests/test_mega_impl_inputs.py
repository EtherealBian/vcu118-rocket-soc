from copy import deepcopy
import json
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
API=runpy.run_path(str(ROOT/'scripts/verify-mega-impl-inputs.py'))


class FourWideInputs(unittest.TestCase):
    def test_pad_roles_and_rate_controls(self):
        report=json.loads((ROOT/'docs/perf-physical-rx.json').read_bytes()); inputs=report['cases']['fixed']['inputs']
        sums={'rtl/'+k:v for k,v in inputs.items()};API['shell_review'](sums,report)
        for k in ('AnalogToUInt_1.v','VCU118FPGATestHarness.sv','PowerOnResetFPGAOnly.v'):
            with self.assertRaisesRegex(ValueError,'shell simulation differs'):API['shell_review']({**sums,'rtl/'+k:'x'},report)
        for key in ('raw','fixed'):
            bad=deepcopy(report);bad['cases'][key]['positive'][1]['half_period_ps']=5000
            with self.assertRaisesRegex(ValueError,'controls'):API['shell_review'](sums,bad)

    def test_private_kit_rejects_unlisted_optional_constraints(self):
        with tempfile.TemporaryDirectory() as d:
            kit=Path(d); f=kit/'sources.f';f.write_bytes(b'list\n'); (kit/'CANDIDATE.sha256').write_text(API['h'](f)+'  sources.f\n')
            self.assertEqual(API['seals'](kit),{'sources.f':API['h'](f)})
            (kit/'surprise.xdc').write_text('additional input')
            with self.assertRaisesRegex(ValueError,'unlisted'):API['seals'](kit)

    def test_promotion_rejects_non_target_shape(self):
        contract=runpy.run_path(str(ROOT/'scripts/promote-wide-model.py'))['contract']
        self.assertEqual(contract('Mega',175),('Perf175MegaBoom',(4,128)))
        for family,freq in [('Mega',150),('unknown',175)]:
            with self.assertRaises(ValueError):contract(family,freq)
