from pathlib import Path
import runpy
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
merge=runpy.run_path(str(ROOT/'scripts'/'prepare-halt-merge.py'))
compare=runpy.run_path(str(ROOT/'scripts'/'compare-halt-traces.py'))['compare']

class SplitIrqTests(unittest.TestCase):
    def test_rewire_only_outer_combiner(self):
        t='''  TLDebugModuleOuterAsync dmOuter (
    .auto_int_out_sync_0                    (auto_dmOuter_int_out_sync_0),
    .io_hgDebugInt_0                        (_dmInner_io_hgDebugInt_0)
  );
  TLDebugModuleInnerAsync dmInner (
    .io_hgDebugInt_0                          (_dmInner_io_hgDebugInt_0),
  );'''
        w=merge['rewire'](t);self.assertIn('halt_on_reset_local (_dmInner_io_hgDebugInt_0)',w); self.assertEqual(w.split('TLDebugModuleInnerAsync')[1],t.split('TLDebugModuleInnerAsync')[1]); self.assertIn('.clk (io_debug_clock)',w)
        for wrong in (t+t,t.replace('dmOuter (','dmOther ('),t.replace('auto_dmOuter_int_out_sync_0','different')):
            with self.assertRaises(ValueError):merge['rewire'](wrong)

    def test_comparison_rejects_data_handshake_length_and_vacuity(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=[Path(tmp)/p for p in ('original','split')]
            for d in (a,b):
                d.mkdir(); (d/'test.ok').touch();(d/'result.txt').write_text(''.join(f'HALT_MERGE_CASE_PASS half={h} phase={p} dmi_transactions=16 ticks=4\n' for h in (4,5,7) for p in (0,1,3)))
            old=bytes([0,1,3,2])*9; new=bytes([0,0,1,1])*9
            (a/'events.bin').write_bytes(old);(b/'events.bin').write_bytes(new);self.assertEqual(compare(a,b),(36,18))
            for wrong in (old,new[:-1],bytes([4])+new[1:],bytes([64])+new[1:]):
                (b/'events.bin').write_bytes(wrong)
                with self.assertRaises(ValueError):compare(a,b)
            for d in (a,b):(d/'events.bin').write_bytes(bytes(36))
            with self.assertRaises(ValueError):compare(a,b)

    def test_refuses_unpinned_synthesis_graph_before_modification(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit=Path(tmp);(kit/'rtl').mkdir(); f=kit/'rtl'/'ChipTop.sv';f.write_bytes(b'other config')
            with self.assertRaisesRegex(ValueError,'unreviewed graph'):merge['install'](kit)
            self.assertEqual(list((kit/'rtl').iterdir()),[f]);self.assertFalse((kit/'sources.f').exists())
