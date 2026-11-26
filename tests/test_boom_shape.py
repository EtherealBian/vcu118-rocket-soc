import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('shape',Path(__file__).resolve().parents[1]/'scripts/check-boom-shape.py'); shape=importlib.util.module_from_spec(spec);spec.loader.exec_module(shape)

class Shape(unittest.TestCase):
    def test_rob_storage_and_commit_connection(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); chain=('ChipTop','DigitalTop','TilePRCIDomain','BoomTile','BoomCore')
            def module(name,lines): (p/(name+'.sv')).write_text('module '+name+'();\n'+'\n'.join(lines)+'\nendmodule\n')
            for parent,child in zip(chain,chain[1:]):module(parent,[child+' u();'])
            ports=[f'io_commit_{key}_{i}' for key in ('valids','arch_valids') for i in range(2)]
            module('BoomCore',['DecodeUnit decode_units_0();','DecodeUnit decode_units_1();','Rob rob('+', '.join(f'.{x}(signal)' for x in ports)+');'])
            regs=['rob_val_0','rob_val_1','rob_val_1_0','rob_val_1_1']
            logic=[f'assign {x} = a;' for x in ports]+[f'reg {r};' for r in regs]+[f'always @(posedge clk) {r} <= a;' for r in regs]
            module('Rob',logic); self.assertEqual(shape.check(p,2,4)['rob_rows_per_bank'],2)
            with self.assertRaises(ValueError):shape.check(p,2,8)
            module('Rob',logic[:-1]);
            with self.assertRaises(ValueError):shape.check(p,2,4)
            module('Rob',logic[1:]);
            with self.assertRaises(ValueError):shape.check(p,2,4)
