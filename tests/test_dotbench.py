import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from dotbench_report import checksum, review
spec=importlib.util.spec_from_file_location('model',ROOT/'scripts/review-uart-dot4-rtl.py')
model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
spec=importlib.util.spec_from_file_location('physical',ROOT/'scripts/verify-soc-capture.py')
physical=importlib.util.module_from_spec(spec);spec.loader.exec_module(physical)


def guest():
    rows=['DOTBENCH_START v1 vectors=257']
    for r,pair in enumerate((('scalar','mmio'),('mmio','scalar'))*2):
        for k in pair:
            t=13 if k=='scalar' else 22
            rows.append(f'DOTBENCH {k} round={r} checksum=3767693399 retired=4500 cycles={1000*t} mtime={t}')
    return rows+['DOTBENCH_PASS vectors=257 rounds=4']


class DotBench(unittest.TestCase):
    def test_independent_checksum_and_ratio_direction(self):
        self.assertEqual(checksum(),3767693399)
        r=review(guest());self.assertEqual(len(r['windows']),8)
        self.assertEqual(r['median_cycles'],dict(scalar=13000,mmio=22000))
        self.assertGreater(r['mmio_to_scalar_elapsed_ratio'],1)

    def test_no_missing_or_corrupted_window(self):
        g=guest()
        for bad in (g[:-1],g[:2]+g[3:],g[:1]+[g[2],g[1]]+g[3:],g+[g[-1]]):
            with self.assertRaises(ValueError):review(bad)
        for old,new in [('round=0','round=2'),('3767693399','3767693398'),('retired=4500','retired=0'),('cycles=13000','cycles=3000'),('mtime=13','mtime=1000')]:
            with self.subTest(old=old),self.assertRaises(ValueError):review([g[0],g[1].replace(old,new),*g[2:]])

    def test_board_and_model_have_distinct_envelopes(self):
        prefix=['UART5_READY v1','UART5_HANDOFF'];g=prefix+guest()
        def raw(rows):return ('\n'.join(rows)+'\n').encode('ascii')
        r=physical.check_uart(raw(g),'dotbench',None);self.assertEqual(len(r['dot_benchmark']['windows']),8)
        end='ROCKET_RTL_PASS mode=uart5-dotbench cycles=12000000 sectors_started=0 tl_read_transactions=7 tl_write_transactions=0 (behavioral RAM/card, no physical DDR)'
        sim=g+['',end];self.assertEqual(model.inspect('uart5-dotbench',sim)['sd_commands'],0)
        for bad in (g,sim[:-2]+[end],sim[1:],sim[:-1]+[end.replace('sectors_started=0','sectors_started=1')],['UART5_REA'+g[2]]+sim[3:]):
            with self.assertRaises(ValueError):model.inspect('uart5-dotbench',bad)
        for bad in (sim,g[1:],g+['unexpected']):
            with self.assertRaises(ValueError):physical.check_uart(raw(bad),'dotbench',None)
