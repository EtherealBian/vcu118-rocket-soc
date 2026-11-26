import importlib.util
from pathlib import Path
import unittest


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/'scripts'/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

pins=load('audit-board-pins'); cross=load('inventory-mig-crossings'); cdc=load('inventory-cdc')

class BoundaryTests(unittest.TestCase):
    want={'sys_clock_p':('E12','INPUT','DIFF_SSTL12','71','FIXED'),'sys_clock_n':('D12','INPUT','DIFF_SSTL12','71','FIXED')}
    report='| Total User IO |\n+---+\n| 2 |\n| Pin Number | Signal Name | Use | IO Standard | IO Bank | Constraint |\n| E12 | sys_clock_p | INPUT | DIFF_SSTL12 | 71 | FIXED |\n| D12 | sys_clock_n | INPUT | DIFF_SSTL12 | 71 | FIXED |\n'
    def test_complete_pin_inventory(self): self.assertEqual(pins.audit_io(self.report,self.want)['io_banks'],{'71':2})
    def test_swapped_polarity_or_voltage_or_direction_rejected(self):
        for old,new in [('E12','D12'),('INPUT','OUTPUT'),('DIFF_SSTL12','LVCMOS18'),('71','72'),('FIXED','DEFAULT'),('sys_clock_n','sys_clock_x'),('| 2 |','| 3 |')]:
            with self.subTest(old=old),self.assertRaises(ValueError):pins.audit_io(self.report.replace(old,new),self.want)
    def test_report_silently_missing_or_duplicate_row(self):
        for bad in [self.report.rsplit('| D12',1)[0],self.report+self.report.splitlines()[-1]+'\n']:
            with self.assertRaises(ValueError):pins.audit_io(bad,self.want)
    def test_crossing_corner_and_interaction_reconciliation(self):
        a,b=cross.SYS,cross.UI; header='source_clock\tdestination_clock\tkind\tstart\tend\tdatapath_ns\tlogic_levels\n'
        pairs=[(a,b,cross.SYSQ+'nodeOut_aw_source/widx_gray_reg[1]/C',cross.UIQ+'nodeOut_aw_sink/widx_widx_gray/output_chain_1/sync_2_reg/D'),(b,a,cross.UIQ+'nodeOut_aw_sink/ridx_gray_reg[1]/C',cross.SYSQ+'nodeOut_aw_source/ridx_ridx_gray/output_chain_1/sync_2_reg/D')]
        tsv=header+''.join('\t'.join((s,d,k,l,r,'1.1','0'))+'\n' for s,d,l,r in pairs for k in ['max','min']); inter=''.join(f'{s}  {d}  0  1  Ignored  Asynchronous Groups\n' for s,d,*_ in pairs)
        self.assertEqual(cross.inventory(tsv,inter)[a+' -> '+b]['captures'],{'gray':1})
        for bad,table in [(tsv,inter.replace('0  1','0  2')), (tsv.replace('chain_1','chain_2',1),inter), (tsv.replace('widx_gray_reg','unreviewed',1),inter),(tsv.replace('1.1','nan',1),inter),(tsv+tsv.splitlines()[-1],inter),(tsv.rsplit('\n',2)[0]+'\n',inter)]:
            with self.assertRaises(ValueError):cross.inventory(bad,table)
    def test_buffered_debug_critical_is_not_disguised_as_clean(self):
        row={'rule':'CDC-10','from':'chiptop0/system/tlDM/dmOuter/dmOuter/debugIntRegs_0_reg/C','to':'chiptop0/system/tile_prci_domain/intsink/chain/output_chain/sync_2_reg/D'}
        self.assertIn('combinational',cdc.family(row));self.assertEqual(cdc.family(dict(row,to=row['to'].replace('2_reg','1_reg'))),'unclassified')

if __name__=='__main__':unittest.main()
