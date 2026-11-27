import runpy
from decimal import Decimal as D
from pathlib import Path
import unittest

M=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-wdata-pin-controls.py'))
Q=M['QUEUE']; mux=M['mux']; pin=M['pin']


class WDataControls(unittest.TestCase):
    def test_physical_fanout_and_paired_delays(self):
        arcs={}; observed=[(s,5) for s in (1,3,6,7)]
        for b in range(64):
            q=mux(b)
            for s in range(8):arcs[q+'/O',pin(s,b)]=D(s+1)
            for i,(src,d) in enumerate(((Q+f'ram_reg[{b}]/Q',7),(Q+'full_reg/Q',9),('mig/buffer/nodeOut_a_q/ram_ext/m/RAMA/O',8 if b==5 else 9))):
                arcs[src,q+f'/I{i}']=D(d)
        inspect=lambda edges:M['trace'](edges,observed)
        good=inspect(arcs); self.assertEqual(good['bits_with_bypass_wire_longer_than_all_eight_output_wires'],63)
        self.assertEqual(good['bit5']['tight_output_wire_max_ps_by_slot'],{'1':'2','3':'4','6':'7','7':'8'})
        for new,remove in [((mux(5)+'/O','other/D'),None),(('other/Q',pin(1,5)),None),(None,(mux(5)+'/O',pin(0,5))),
                           ((Q+'full_reg/Q',mux(5)+'/I2'),('mig/buffer/nodeOut_a_q/ram_ext/m/RAMA/O',mux(5)+'/I2'))]:
            bad=arcs.copy()
            if remove:del bad[remove]
            if new:bad[new]=D(1)
            with self.assertRaises(ValueError):inspect(bad)

    def test_lut_truth_and_independent_data_pins(self):
        q='\n'.join(f"  LUT3 #(\n    .INIT(8'hB8))\n    \\{mux(b)[len(Q):]}  (" for b in range(64))
        w='\n'.join(f'  FDRE \\mem_{s}_data_reg[{b}]  (.C(clk),.D(data[{b}]),.Q(q));' for s in range(8) for b in range(64))
        check=M['check_verilog_text'];check(q,w)
        for q1,w1 in [(q.replace('B8','B0',1),w),(q+q,w),(q,w.replace('data[2]','data[1]',1)),(q,w.replace('data[2]','data[1]'))]:
            with self.assertRaises(ValueError):check(q1,w1)
