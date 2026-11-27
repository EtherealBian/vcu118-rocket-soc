from decimal import Decimal
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import unittest

m = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-aw-control-fanout.py'))
AW, RX, SH = (m[k] for k in ('AW','RX','SHARED'))
D = Decimal


def bank():
    flops, types, inputs, outs = {}, {SH:'LUT3'}, {}, set()
    for s in range(8):
        g = f'decoder{s}'
        types[AW+g] = 'LUT5'
        inputs[AW+g+'/I4'] = (SH+'/O', D(s+1)); outs.add(AW+g+'/I4')
        for i in range(4):
            inputs[AW+g+f'/I{i}'] = (AW+f'widx_gray_reg[{i}]/Q', D(1))
        for field, indices in [('addr', [0,*range(5,31)]), ('id', range(4)), ('len',range(8)), ('size',range(2))]:
            for i in indices:
                bit = f'mem_{s}_{field}_reg[{i}]'; flops[bit] = g; types[AW+bit]='FDRE'
                inputs[AW+bit+'/CE'] = (AW+g+'/O', D(i+1))
    for i in range(3):
        inputs[SH+f'/I{i}'] = (('mig/toaxi4/queue_arw_deq_q/full_reg/Q' if i==0 else f'other{i}/O'),D(1))
    outs.update(f'other{i}/I1' for i in range(9))
    return flops, types, inputs, outs


class TestRoutedAW(unittest.TestCase):
    def test_slot_driver_crosscheck(self):
        flops, types, inputs, outs = bank(); result=m['trace'](flops,types,inputs,outs)
        self.assertEqual((result['physical_ce_pins'],result['shared_output_sink_pins']),(328,17))
        self.assertEqual(result['decoder_to_ce_wire_max_ps_range'],['1','31'])
        dest = AW+'mem_2_len_reg[6]/CE'; inputs[dest]=(AW+'decoder1/O',D(2))
        with self.assertRaisesRegex(ValueError,'driver mismatch'): m['trace'](flops,types,inputs,outs)
        del inputs[dest]
        with self.assertRaisesRegex(ValueError,'payload bits differ'): m['trace'](flops,types,inputs,outs)

    def test_shared_output_and_four_pointer_pins(self):
        f,t,i,o=bank()
        with self.assertRaisesRegex(ValueError,'sink inventory'): m['trace'](f,t,i,o-{'other8/I1'})
        i[AW+'decoder0/I0']=(AW+'widx_gray_reg[1]/Q',D(1))
        with self.assertRaisesRegex(ValueError,'pointer bits'): m['trace'](f,t,i,o)
        del i[AW+'decoder0/I0']
        with self.assertRaisesRegex(ValueError,'missing slot decoder pin'): m['trace'](f,t,i,o)

    def test_timesim_sdf_rise_fall_and_pin_direction(self):
        bit='mem_0_id_reg[0]'; net='mem_0_id_reg[3]_0[0]'; c=RX+'mux[0]'
        with TemporaryDirectory() as tmp:
            v=Path(tmp)/'top.v'; sdf=Path(tmp)/'top.sdf'; v.write_text(
                'module AsyncQueueSource_AXI4BundleAW\n'
                "  LUT5 #(\n    .INIT(32'h00000090)) \\dec[0] \n    (.O(\\en[0] ));\n"
                '  FDRE \\'+bit+' \n    (.D(d), .CE(\\en[0] ), .Q(\\mem_0_id_reg[3]_0 [0]));\nendmodule\n')
            enables, pins=m['netlist'](v); self.assertEqual(enables, {bit:'dec[0]'})
            hd='(DELAYFILE\n(SDFVERSION "3.0" )\n(DESIGN "VCU118FPGATestHarness")\n(DATE "")\n(VENDOR "XILINX")\n(PROGRAM "Vivado")\n(VERSION "2024.2")\n(DIVIDER /)\n(TIMESCALE 1ps)\n'
            body=(f'(CELLTYPE "LUT6")\n(INSTANCE {c})\n(INTERCONNECT {AW}{bit}/Q {c}/I0 (1:2:3) (1:4:8))\n'
                  f'(INTERCONNECT {AW}dec[0]/O {AW}{bit}/CE (1:7:9) (1:4:5))\n').replace('[',r'\[').replace(']',r'\]')
            sdf.write_text(hd+body); t,i,_,outs,_=m['sdf'](sdf,{bit:net})
            self.assertEqual(i[AW+bit+'/CE'][1],D(9))
            result=m['trace_moves']({bit:net},pins,t,outs); self.assertEqual(result['Q_to_first_sink_wire_max_ps_range'],['8','8'])
            with self.assertRaisesRegex(ValueError,'uniquely match'): m['trace_moves']({bit:'d'},pins,t,outs)
            with self.assertRaisesRegex(ValueError,'first physical sink'): m['trace_moves']({bit:net},pins,{c:'FDRE'},outs)
            with self.assertRaisesRegex(ValueError,'Q fanout'): m['trace_moves']({bit:net},pins,t,{})
            sdf.write_text(hd.replace('1ps','1ns')+body)
            with self.assertRaisesRegex(ValueError,'units'): m['sdf'](sdf,{bit:net})

    def test_neither_control_accepts_another_export(self):
        pins = m['EXPORTS']; a,b=pins
        for first,second in ((a,b),(b,a)):
            m['bind'](first,pins[first])
            for idx in range(4):
                bad=list(pins[first]); bad[idx]=pins[second][idx]
                with self.assertRaisesRegex(ValueError,'mixed'): m['bind'](first,tuple(bad))

    def test_missing_actual_four_wide_physopt(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'log'; p.write_bytes(b'\nVCU118_STAGE=place\n\nCommand: phys_opt_design -directive Explore\nwrong')
            with self.assertRaisesRegex(ValueError,'different or incomplete'): m['moved_pairs'](p)
