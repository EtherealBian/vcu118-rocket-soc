from pathlib import Path
import runpy
import unittest

inv=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts'/'board_io_inventory.py'))

def report(inputs,outputs):
    return '\n'.join(f'{i}. checking no_{d}_delay ({len(names)})\n-----------------------\n There are {len(names)} ports with no {d} delay specified. (HIGH)\n\n'+ '\n'.join(names)+f'\n\n There are 0 ports with no {d} delay but user has a false path constraint.\n' for i,d,names in [(5,'input',inputs),(6,'output',outputs)])

def check(i,o,src=None):
    return inv['check_io'](report(i,o) if src is None else src,{'no_input_delay':len(i),'no_output_delay':len(o)})

class BoardIOTests(unittest.TestCase):
    def test_known_port_is_not_external_timing_approval(self):
        i=['reset','sdio_spi_dat_0'];o=['sdio_spi_dat_3','sdio_spi_cs'];x,known=check(i,o); self.assertTrue(known);self.assertIn('MOSI',x['output']['unconstrained_ports']['sdio_spi_cs'][1]);self.assertTrue(check([],[])[1]);self.assertFalse(check(['untimed_pin'],[])[1]);self.assertFalse(check([],['uart_rxd'])[1])
    def test_rejects_missing_duplicate_or_inconsistent_detail(self):
        i=['uart_rxd','reset'];o=[];s=report(i,o)
        for wrong in [s.replace('\nuart_rxd\n','\n'),s.replace('\nuart_rxd\n','\nreset\n'),s+s,s.replace('There are 2 ports','There are 3 ports')]:
            with self.assertRaises(ValueError):check(i,o,wrong)
    def test_additional_exemptions_do_not_pass(self):
        i=['uart_rxd'];o=[];s=report(i,o).replace('0 ports with no input delay but','1 port with no input delay but');x,known=check(i,o,s);self.assertFalse(known);self.assertTrue(x['input']['additional_nonzero_checks'])
