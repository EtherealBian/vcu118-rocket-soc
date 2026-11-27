from pathlib import Path
import runpy
import unittest

HERE=Path(__file__).resolve().parents[1]/'scripts'
C=runpy.run_path(str(HERE/'review-mega-shell-constraints.py'))
D=runpy.run_path(str(HERE/'review-mega-linux-contract.py'))
G=runpy.run_path(str(HERE/'check-mega-way-candidate.py'))

class StaticInputTests(unittest.TestCase):
    def test_boot_identity_rejects_other_machine_or_byte_order(self):
        p=D['MACHINE_PROPERTIES']; self.assertEqual(len(D['identity'](p)),3)
        for key,bad in [(k,v[::-1]) for k,v in p.items()]+[('/cpus/cpu@1/compatible',b'riscv')]:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'boot properties'):
                D['identity']({**p,key:bad})
    def test_pll_request_is_only_permitted_change(self):
        def pll(f,low,high):return f'CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {{{f}.0}}\nif {{$freq < {low} || $freq > {high}}}\noutside tolerated range {low}-{high}\n'.encode()
        low=pll(100,'99.0','101.0'); high=pll(175,'173.25','176.75'); C['pll_delta'](low,high)
        for bad in (high.replace(b'175.0',b'150.0'),high.replace(b'176.75',b'200.0'),high+b'set_false_path\n'):
            with self.assertRaises(ValueError):C['pll_delta'](low,bad)
    def test_retiming_rejects_foreign_input_without_output(self):
        with self.assertRaisesRegex(ValueError,'unexpected four-wide'):G['transform'](b'module Other; endmodule\n')

if __name__=='__main__':unittest.main()
