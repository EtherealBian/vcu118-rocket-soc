from pathlib import Path
import runpy
import unittest

R = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-address-chain.py'))


class ReachingPointer(unittest.TestCase):
    def setUp(self):
        A, L = R['Request'], R['Result']
        self.args = [A(12,1,17,3,0x200,0x208),L(15,0,17,3,0x400,'C'),
                     A(17,0,56,9,0x400,0x402),L(20,1,56,9,0xffffffffffffffff,'F'),
                     19,22,(20,1,56,0xffffffffffffffff)]

    def test_independent_return_lanes(self):
        R['chain'](*self.args)

    def test_coherent_but_wrong_address_or_queue(self):
        a,p,b,k,*_ = self.args
        for n,x in [(0,a._replace(ea=a.base)),(1,p._replace(pdst=56)),(1,p._replace(ldq=9)),
                    (2,b._replace(base=b.base+8,ea=b.ea+8)),(2,b._replace(tick=p.tick-1)),
                    (3,k._replace(value=k.value^1)),(4,p.tick-1)]:
            args=self.args.copy(); args[n]=x
            with self.subTest(n=n,x=x),self.assertRaises(ValueError): R['chain'](*args)

    def test_capture_rejects_unpaired_reused_or_invalid_tickets(self):
        trace='A 12 259 1 17 3 512 520\nC 15 259 0 17 3 1024'; req,res=R['parse'](trace)
        self.assertEqual(req[259].ldq,3); self.assertEqual(res[259].source,'C')
        for bad in [trace.splitlines()[0],trace+'\n'+trace.splitlines()[0],trace.replace('12 259','2 259'),
                    trace.replace('1 17 3','1 17 32'),trace.replace('C 15','X 15'),trace.replace('1024',str(1<<64))]:
            with self.subTest(bad=bad),self.assertRaises(ValueError): R['parse'](bad)
