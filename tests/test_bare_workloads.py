from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from counter_report import review as counters
from sweep_report import review as sweep


class WorkloadChecks(unittest.TestCase):
    def test_counter_windows(self):
        n=131072; rows=['VCU118_COUNTER_START v1 n=131072']
        # Each expected count is derived from the explicit loop body and the initial CSR read.
        for r in range(3):
            for k,acc,ret in [('chain-add',n,3*n+1),('load-use',3*n,4*n+1),('branch-alt',n,4*n+n//2+1)]:
                rows.append(f'COUNTER {k} round={r} result={acc} retired={ret} cycles=750050 mtime=750')
        rows.append('VCU118_COUNTER_PASS kernels=3 rounds=3');self.assertEqual(len(counters(rows)),9)
        for wrong in (rows[:-2]+rows[-1:],rows[:1]+[rows[2],rows[1]]+rows[3:],*[rows[:1]+[rows[1].replace(a,b)]+rows[2:] for a,b in [('retired=393217','retired=393216'),('result=131072','result=131071'),('mtime=750','mtime=650'),('cycles=750050','cycles=750')]]):
            with self.assertRaises(ValueError):counters(wrong)

    def test_sweep_all_phases(self):
        rows=['VCU118_SWEEP_START v1 block_mib=8 blocks=254']+[f'SWEEP pass={p} {k} blocks={b} ticks={b*21}' for p in (0,1) for k in ('write','read') for b in (64,128,192,254)]+['VCU118_SWEEP_PASS bytes=2130706432 passes=2']
        self.assertEqual(sweep(rows)['unique_bytes'],2032*1024**2)
        for bad in (rows[:-2]+rows[-1:],rows[:7]+rows[8:],rows[:2]+[rows[2].replace('2688','100')]+rows[3:],rows[:1]+[rows[1].replace('write','read')]+rows[2:],rows[:-1]+[rows[-1].replace('2130706432','2147483648')]):
            with self.assertRaises(ValueError):sweep(bad)
