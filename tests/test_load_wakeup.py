from pathlib import Path
import runpy
import tempfile
import unittest

api = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/check-load-wakeup.py'))


def write_fixture(rtl, fast):
    keys = [api['ORDINARY'], *(api['NAMES'] if fast else ())]
    wires = '\n'.join(f'wire _lsu_io_core_{k};' for k in keys)
    def conn(prefix):
        return ',\n'.join(f'.io_{prefix}_{k}(_lsu_io_core_{k})' for k in keys)
    def ports(direction, prefix):
        return ',\n'.join(f'{direction} io_{prefix}_{k}' for k in keys)
    drivers = '\n'.join(f'assign io_core_{k} = io_dmem_valid;' for k in keys)
    sinks = ',\n'.join(f'.sink_{k}(io_lsu_{k})' for k in keys)
    texts = {'BoomTile':f'();\n{wires}\nLSU lsu({conn("core")});\nBoomCore core({conn("lsu")});',
             'BoomCore':f'({ports("input", "lsu")});\nConsumer u({sinks});',
             'LSU':f'(input io_dmem_valid, {ports("output", "core")});\n{drivers}'}
    for m, body in texts.items():
        (rtl/(m+'.sv')).write_text(f'module {m}{body}\nendmodule\n')


class LoadWakeup(unittest.TestCase):
    def test_stock_and_candidate_are_not_interchangeable(self):
        with tempfile.TemporaryDirectory() as d:
            x, y = Path(d)/'stock', Path(d)/'candidate'; x.mkdir(); y.mkdir()
            write_fixture(x, True); write_fixture(y, False)
            r = api['check'](x, y)
            self.assertEqual(r['no_fast_load']['speculative_ports'], [])
            for a, b in ((x,x), (y,y), (y,x)):
                with self.assertRaises(ValueError): api['check'](a,b)

    def test_ties_crosswires_and_missing_consumers_rejected(self):
        changes = [('LSU','assign io_core_ld_miss = io_dmem_valid;',"assign io_core_ld_miss = 1'b0;"),
                   ('BoomTile','.io_lsu_exe_0_iresp_valid(_lsu_io_core_exe_0_iresp_valid)', '.io_lsu_exe_0_iresp_valid(_lsu_io_core_ld_miss)'),
                   ('BoomCore','.sink_spec_ld_wakeup_0_valid(io_lsu_spec_ld_wakeup_0_valid)', '.sink_spec_ld_wakeup_0_valid(1\'b0) /* .fake(io_lsu_spec_ld_wakeup_0_valid) */')]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for module, old, new in changes:
                with self.subTest(module=module):
                    write_fixture(root, True); p = root/(module+'.sv'); t = p.read_text()
                    self.assertEqual(t.count(old), 1); p.write_text(t.replace(old, new))
                    with self.assertRaises(ValueError): api['check_variant'](root, True)
