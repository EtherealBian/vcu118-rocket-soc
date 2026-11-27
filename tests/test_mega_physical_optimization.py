from pathlib import Path
import runpy
import unittest

HERE=Path(__file__).resolve().parents[1]/'scripts'
report=runpy.run_path(str(HERE/'inspect-mega-postroute.py'))
mapping=runpy.run_path(str(HERE/'map-mega-regfile.py'))
derive=runpy.run_path(str(HERE/'derive-mega-regfile.py'))

class PhysicalOptimizationControls(unittest.TestCase):
    def test_endpoint_reopen_does_not_accept_a_different_launch(self):
        orig=[dict(slack_ns='-1.000',destination_clock='clk_out1_harnessSysPLL',kind='max',**{'from':'a','to':f'b{i}'}) for i in range(40)]
        dst=[dict(slack_ns=r['slack_ns'],start=r['from'],end=r['to']) for r in orig[::-1]]
        report['reconcile'](orig,dst,'max')
        for wrong in (dst[:-1], [*dst[:-1],dst[1]], [{**dst[0],'start':'c'},*dst[1:]], [{**dst[0],'slack_ns':'1.000'},*dst[1:]]):
            with self.assertRaises(ValueError):report['reconcile'](orig,wrong,'max')
        with self.assertRaises(ValueError):report['reconcile'](orig,dst,'min')

    def test_mapping_primitive_accounting(self):
        text='=== demo ===\n   Number of processes: 0\n   Number of memories: 0\n   Number of cells: 15\n     FDRE 10\n     LUT6 5\nchecking module demo..\nfound and reported 0 problems.\n'
        self.assertEqual(mapping['table'](text,'demo'),{'FDRE':10,'LUT6':5})
        for bad in [text*2,text.replace('15','16'),text.replace('LUT6','arbitrary'),text.replace('0 problems','1 problems'),text.replace('memories: 0','memories: 2')]:
            with self.assertRaises(ValueError):mapping['table'](bad,'demo')

    def test_adapter_port_contract_and_packing(self):
        io=[]
        for prefix,n in (('R',2),('W',2)):
            for i in range(n):
                io += [f'input [6:0] {prefix}{i}_addr',f'input {prefix}{i}_en',f'input {prefix}{i}_clk',('output' if prefix=='R' else 'input')+f' [63:0] {prefix}{i}_data']
        stock='module regfile_128x64('+', '.join(io)+');\nendmodule\n'; a=derive['adapter'](stock,64,2,2)
        for conn in ('.clock(W0_clk)','.raddr({R1_addr, R0_addr})','.rdata({R1_data, R0_data})','.wdata({W1_data, W0_data})'):
            self.assertIn(conn,a)
        for wrong in (stock.replace('[6:0]','[5:0]',1),stock.replace(' W1_en',' W0_en'),stock.replace('output','input',1)):
            with self.assertRaises(ValueError):derive['adapter'](wrong,64,2,2)
