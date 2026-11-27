"""Synthetic, non-vendor fixtures for the S1 path report review."""
import csv
from pathlib import Path
import runpy
import tempfile
import unittest

API = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-mshr-way-inputs.py'))
CLK, BASE = API['CLOCK'], API['BASE']


def make(root):
    with (root/'paths.tsv').open('w',newline='') as f:
        writer=csv.writer(f,delimiter='\t'); writer.writerow(API['HEADER'])
        for sink,width in API['SINKS'].items():
            for bit in range(width):
                src = BASE + ('meta_0/tag_array/tag_array_ext/mem_0_0/ram_RW_0_r_addr_pipe_0_reg[1]/C' if width==8 else f'lfsr_prng/state_{bit}_reg/C')
                dst=f'{BASE}{sink}[{bit}]/D';levels = int(width==8)
                writer.writerow([sink,bit,src,dst,levels,'1.000','4.000','5.714'])
                edge=f'(rising edge-triggered cell FDRE clocked by {CLK} {{rise@0.000ns fall@2.857ns period=5.714ns}})'
                (root/f'{sink}-{bit}.rpt').write_text(f'''| Tool Version : Vivado v.2024.2 (test)
| Design : VCU118FPGATestHarness
| Device : xcvu9p-flga2104
| Design State : Optimized
Slack (MET) : 4.000ns (estimate)
  Source: {src}
    {edge}
  Destination: {dst}
    {edge}
  Path Group: {CLK}
  Path Type: Setup (Max at Slow Process Corner)
  Requirement: 5.714ns (requirement)
  Data Path Delay: 1.000ns (logic 0.400ns (40%) route 0.600ns (60%))
  Logic Levels: {levels}
net (fo=1, unplaced)
''')


class Arrivals(unittest.TestCase):
    def test_each_bit_and_aggregate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);make(root);r=API['review'](root)
            self.assertEqual([g['endpoints'] for g in r['groups'].values()], [8,3]); self.assertEqual(len(r['inputs_sha256']),12)
            table=root/'paths.tsv'; t=table.read_text(); table.write_text(t.replace('_reg\t7\t','_reg\t6\t'))
            with self.assertRaisesRegex(ValueError,'duplicate/missing'):API['review'](root)

    def test_rejects_other_stage_bits_clocks_and_inconsistent_values(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);make(root); p=root/'s2_tag_match_way_0_reg-0.rpt'; text=p.read_text()
            for a,b in [('Optimized','Routed'),('/C','/D'),('[0]/D','[1]/D'),('period=5.714ns','period=10ns'),('4.000ns','3.000ns'),('0.400ns','0.200ns'),('Logic Levels: 1','Logic Levels: 2'),('MET','VIOLATED')]:
                p.write_text(text.replace(a,b))
                with self.subTest(change=a),self.assertRaises(ValueError):API['review'](root)

    def test_rejects_substituted_checkpoint_source_and_unfinished_run(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dcp=root/'example.dcp';dcp.write_bytes(b'model');src=Path(API['__file__']).with_name('measure-mshr-way-inputs.tcl');log=root/'run.log'
            t=f'# Current directory : {root}\n# Command line : vivado -source "{src}" -tclargs "{dcp}" "{root}"\nMSHR_WAY_BASELINE_S1_CHECKPOINT_QUERY_COMPLETE\nINFO: [Common 17-206] Exiting Vivado at end\n'
            log.write_text(t);self.assertIn('checkpoint_sha256',API['attach_run']({},root,dcp,log))
            for other in [t.replace(str(dcp),str(log)),t.replace(str(src),str(dcp)),t.replace('QUERY_COMPLETE','NOT_COMPLETE'),t+'ERROR: failed\n']:
                log.write_text(other)
                with self.assertRaises(ValueError):API['attach_run']({},root,dcp,log)
