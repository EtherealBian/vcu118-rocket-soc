"""Synthetic reset cone. Use no placed vendor netlists in unit tests."""
from pathlib import Path
import re
import runpy
import unittest

api=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/trace-medium-reset.py'))
source,pre,mig,por,chains,sysclk,memclk=(api[k] for k in ('SOURCES','PRE','MIG','POR','CHAINS','SYSCLK','MEMCLK'))
lut='mig/island/test_lut'

def toy():
    rows=[{'from':p+'/C','to':pre+'/PRE','severity':'Critical','rule':'CDC-7'} for p in (mig,por)]
    escaped=lambda x:re.sub(r'([.\[\]])',r'\\\1',x)
    def edge(a,b):return f'(INTERCONNECT {escaped(a)} {escaped(b)} (1:1:1) (1:1:1))\n'
    def cell(k,n):return f'(CELLTYPE "{k}")\n(INSTANCE {escaped(n)})\n'
    sdf=''.join(cell(k,v) for k,v in [('LUT4',lut),('FDPE',pre),('FDRE',mig),('FDRE',por),('IBUFCTRL','IBUF/IBUFCTRL_INST'),('MMCME4_ADV','harnessSysPLL/inst/mmcme4_adv_inst')])
    sdf+=''.join(edge(a,lut+'/I'+str(i)) for i,a in enumerate(source.values()))
    sdf+=edge(lut+'/O',pre+'/PRE')+edge(memclk,mig+'/C')+edge('_sys_clock_ibufds_O_BUFG_inst/O',por+'/C')+edge(sysclk,pre+'/C')
    for c,clk in zip(chains,(sysclk,memclk)):
        for i in range(3):
            r=c+str(i)+'_reg'; sdf+=cell('FDCE',r)+edge(pre+'/Q',r+'/CLR')+edge(clk,r+'/C')
            if i<2:sdf+=edge(c+str(i+1)+'_reg/Q',r+'/D')
    net=b'''module VCU118FPGATestHarness ();
XilinxVCU118MIG mig ();
IBUF_UNIQ_BASE_ IBUF (.I(reset), .O(_IBUF_O));
endmodule
module XilinxVCU118MIG ();
XilinxVCU118MIGIsland island ();
endmodule
module XilinxVCU118MIGIsland ();
LUT4 #(.INIT(16'hFFFD)) test_lut (.I0(locked),.I1(_IBUF_O),.I2(rst_r1_alias),.I3(power_on_reset),.O(x));
endmodule'''
    return sdf.encode(),net,rows

class MediumReset(unittest.TestCase):
    def test_truth_and_both_clock_chains(self):
        self.assertEqual(api['trace'](*toy())['truth_table_rows'],16)
    def test_independent_rejections(self):
        sdf,net,rows=toy()
        for actual,old,new in [('sdf',b'/I2 (',b'/I1 ('),('sdf',b'"FDPE"',b'"FDRE"'),('sdf',b'sync_1_reg/Q',b'sync_2_reg/Q'),('sdf',b'clkout1_buf/O',b'clkout2_buf/O'),('net',b'.I(reset)',b'.I(misc)'),('net',b'hFFFD',b'hFFFC'),('net',b'.I2(rst_r1_alias)',b'.I2(power_on_reset)')]:
            with self.subTest(change=old),self.assertRaises(ValueError):
                api['trace'](sdf.replace(old,new) if actual=='sdf' else sdf,net.replace(old,new) if actual=='net' else net,rows)
        for s,r in [(sdf+b'(INTERCONNECT '+pre.encode()+b'/Q other/CLR (1:1:1))\n',rows),(sdf,rows[:1]),(sdf+b'(INTERCONNECT other/O '+pre.encode()+b'/PRE (1:1:1))\n',rows)]:
            with self.assertRaises(ValueError):api['trace'](s,net,r)
