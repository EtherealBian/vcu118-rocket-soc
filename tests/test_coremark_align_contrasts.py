import runpy
import unittest
from pathlib import Path

m=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/coremark-align-contrasts.py'))


class Compare(unittest.TestCase):
    def setUp(self):
        names=m['NAMES'];self.order=[names[(i+j)%4] for i in range(3) for j in range(4)]
        self.matrix=dict(order=self.order,clock_mhz=100,total_buffer_bytes=2000,iterations_each_seed_set=12000,profiles={});self.code={'profiles':[]}
        for i,p in enumerate(names):
            self.code['profiles'].append(dict(profile=p,elf_sha256=p,effective_strict_align=i<2,explicit_mtune='generic-ooo' if i in (1,2) else None))
            speed=([100,200,300] if i!=1 else [101,400,297]); self.matrix['profiles'][p]=dict(elf_sha256=p,measurements=[dict(sequence=j+1,runs={s:dict(iterations_per_s=str(speed[j//4])) for s in ('performance','validation')}) for j,q in enumerate(self.order) if q==p])

    def test_paired_contrasts_not_ratio_of_medians(self):
        v=m['compare'](self.matrix,self.code)['contrasts']['tune_at_strict'];self.assertEqual(v['sequence_pairs'],[[1,2],[8,5],[11,12]])
        self.assertEqual(v['performance']['median_paired_change_pct'],'1.000000');self.assertEqual(v['performance']['ratio_of_medians_change_pct'],'48.500000')

    def test_reject_foreign_factor_and_repeat(self):
        p=m['NAMES'][1];v=self.code['profiles'][1];v['effective_strict_align']=False
        with self.assertRaisesRegex(ValueError,'factor'):m['compare'](self.matrix,self.code)
        v['effective_strict_align']=True;self.matrix['profiles'][p]['measurements'][1]['sequence']=2
        with self.assertRaisesRegex(ValueError,'acquisition'):m['compare'](self.matrix,self.code)
