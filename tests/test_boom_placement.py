import runpy
import unittest
from pathlib import Path

m=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-boom-placement.py'))


class PlacerTables(unittest.TestCase):
    def setUp(self):
        one='|           | Global Congestion | Long Congestion   | Short Congestion  |\n'+''.join('| '+d+'| 1x1| 2x2| 4x4|\n' for d in ('North','South','East','West'))
        self.tables=one+''.join('SLR%d:\n%s'%(i,one) for i in range(3))

    def test_direction_and_region_are_not_interchangeable(self):
        r=m['regions'](self.tables.replace('| East| 1x1| 2x2| 4x4|','| East| 8x8| 32x32| 4x4|',1))
        self.assertEqual(r['device']['East']['long'],'32x32')
        self.assertEqual(r['SLR0']['East']['long'],'2x2')
        self.assertEqual(len(r['SLR2']),4)

    def test_reject_incomplete_or_ambiguous_tables(self):
        for old,new in [('SLR1:', 'SLR0:'), ('| South|','| West|'), ('Long Congestion','Short Congestion'), ('4x4|','absent|')]:
            with self.subTest(old=old),self.assertRaises(ValueError):m['regions'](self.tables.replace(old,new,1))
