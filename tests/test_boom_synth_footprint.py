"""Test cell-table parsing without a vendor tool or a design checkpoint."""
from pathlib import Path
import runpy
import unittest

F = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-boom-synth-footprint.py'))


class SynthTable(unittest.TestCase):
    def setUp(self):
        self.rows = [f'|{i:3d} |{key:12} | {3*i}|' for i,key in enumerate(F['KEYS'],1)]
        self.header = ['Report Cell Usage: ','+---+---+---+','|    |Cell         |Count  |','+---+---+---+']

    def text(self,rows): return '\n'.join(self.header+rows+['+---+---+---+'])

    def test_counts_ignore_neighboring_text(self):
        counts,_ = F['cell_table']('other report\n'+self.text(self.rows)+'\nnext report')
        self.assertEqual(counts['LUT6'],18); self.assertEqual(len(counts),len(self.rows))

    def test_incomplete_duplicated_and_spliced_tables_fail(self):
        for text in (self.text(self.rows[:-1]), self.text(self.rows[:-1]+[self.rows[0]]),
                     self.text(self.rows)+'\n'+self.text(self.rows),self.text(self.rows).replace('LUT1','Bad |LUT1')):
            with self.subTest(text=text), self.assertRaises(ValueError): F['cell_table'](text)
