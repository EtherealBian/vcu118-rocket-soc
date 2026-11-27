from pathlib import Path
import json
import runpy
import unittest

ROOT=Path(__file__).resolve().parents[1]
D=runpy.run_path(str(ROOT/'scripts/derive-copy-load-model.py')); C=D['C']; LEAF=D['LEAF']


class CopyLoad(unittest.TestCase):
    def test_exactly_one_real_delta(self):
        old={LEAF:'a','rtl/Other.sv':'b'};new={**old,LEAF:'c'};D['only_one'](old,new,'c')
        for bad in (old,{}, {LEAF:'c'}, {**new,'new':'b'}, {**new,'rtl/Other.sv':'z'}):
            with self.assertRaises(ValueError):D['only_one'](old,bad,'c')
        with self.assertRaises(ValueError):D['only_one']({}, {LEAF:'c'}, 'c')

    def test_wrong_source_or_ambiguous_edit_refused(self):
        with self.assertRaises(ValueError):C['candidate']('module RenameStage(); endmodule')
        for text in ('', 'twice twice'):
            with self.assertRaises(ValueError):C['once'](text,'twice','ok')

    def test_recorded_fixture_and_model_agree(self):
        test,kit=[json.loads((ROOT/'docs'/n).read_bytes()) for n in ('perf-copy-load-rename.json','perf-copy-load-model.json')]
        self.assertEqual(test['module_sha256'],C['LOCK']); self.assertEqual(test['candidate_sha256'],kit['changed'][LEAF]);
        self.assertEqual(test['bench_sha256'],D['h']((ROOT/'tests/copy_load_rename_tb.v').read_bytes()));self.assertNotEqual(kit['original_seal'],kit['candidate_seal'])
        self.assertEqual(set(test['results']),{'candidate','omit_lane1','ignore_copy_sfb','original_map_read'})
