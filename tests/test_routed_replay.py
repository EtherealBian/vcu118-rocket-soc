from pathlib import Path
import re
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import routed_replay as replay


class RoutedReplay(unittest.TestCase):
    def render(self, path, body, host='build', date='then'):
        cmd = replay.COMMANDS[path.name]
        drc = path.name == 'routed-drc.rpt'
        fields = {'Tool Version': 'Vivado v.2024.2 (test fixture)', 'Date': date, 'Host': host,
                  'Command': cmd + ' -file ' + path.as_posix(), 'Design': 'VCU118FPGATestHarness',
                  'Device': 'xcvu9p-flga2104' + ('-2L-e' if drc else ''), 'Speed File': '-2L',
                  'Design State': 'Fully Routed' if drc else 'Physopt postRoute'}
        head = '\n'.join('| '+key+' : '+value for key,value in fields.items())
        bar = '-' * 25
        return ('Copyright\n'+bar+'\n'+head+'\n'+bar+'\n'+body+'\n').encode()

    def test_default_drc_keeps_named_instances_even_at_equal_counts(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = (Path(d) / n / 'routed-drc.rpt' for n in ['old','new'])
            body = 'Report DRC\nChecks found: 1\n2. REPORT DETAILS\nDPIP-2#1 Warning\nInput pipelining\nDSP unit_a is not pipelined.'
            x, y = self.render(a, body), self.render(b, body, 'audit', 'now')
            sig = lambda p, t: replay.signature(p.name,t,p)
            self.assertEqual(sig(a,x),sig(b,y.replace(b'\n',b'\r\n')))
            self.assertNotEqual(sig(a,x),sig(b,y.replace(b'unit_a',b'unit_b')))
            for bad in (x, y.replace(b'Fully Routed',b'Synthesized'), y.replace(b'report_drc -file',b'report_drc -waived -file')):
                with self.assertRaises(ValueError): sig(b,bad)

    def test_timer_settings_and_all_three_global_checks(self):
        path = Path('full-timing.rpt').resolve()
        body = '''Timing Summary Report
| Timer Settings
 Enable Multi Corner Analysis : Yes
| Report Methodology
| Design Timing Summary
 WNS(ns) TNS(ns) TNS Failing Endpoints TNS Total Endpoints WHS(ns) THS(ns) THS Failing Endpoints THS Total Endpoints WPWS(ns) TPWS(ns) TPWS Failing Endpoints TPWS Total Endpoints
 ------
 -1.0 -2.5 2 120 0.08 0.000 0 110 -0.1 -0.2 2 50
| Clock Summary
| -------------
'''
        def sig(text): return replay.signature(path.name, self.render(path,text), path)
        ref = sig(body)  # A negative setup and a negative pulse slack must remain reportable.
        for old,new in [('2 120','1 120'), ('0.08','-0.08'), ('-0.1','0.1'), ('Yes','No')]:
            self.assertNotEqual(ref,sig(body.replace(old,new)))
        for bad in (body.replace(' 2 50',' 50'), body.replace('| Design Timing Summary','| Clock Timing Summary')):
            with self.assertRaises(ValueError): sig(bad)

    def test_cdc_same_count_and_severity_not_enough(self):
        path = Path('cdc.rpt').resolve()
        body = '''CDC Report
CDC-10  Critical   1  Combinational logic
Source Clock: clk_a
Destination Clock: clk_b
CDC Type: No Common Primary Clock
1  CDC-10  Critical  Combinational logic  2  False Path  source_reg/C  capture_reg/D'''
        def sig(text): return replay.signature(path.name, self.render(path,text), path)
        for old,new in [('clk_b','clk_c'),('capture_reg','other_reg'),('False Path','Asynch Clock Groups')]:
            self.assertNotEqual(sig(body),sig(body.replace(old,new)))
        with self.assertRaises(ValueError): sig(body.replace('   1  Combinational','   2  Combinational'))

    def test_record_mismatch_without_losing_other_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = [Path(d) / n for n in ['a','b']]; a.mkdir(); b.mkdir()
            name = 'route-status.rpt'
            raw = 'Design Route Status\n# of routable nets... : 10 :\n# of fully routed nets... : 10 :\n# of nets with routing errors... : 0 :\n'
            (a/name).write_bytes(raw.encode()); (b/name).write_bytes(raw.replace('10','11').encode())
            records = replay.compare_reports(a,b)
            self.assertEqual(len(records),6)
            self.assertFalse(any(r['matches'] for r in records.values()))
            self.assertIn('compared_sha256',records[name]['original'])
            self.assertIn('compared_sha256',records[name]['reopened'])
            self.assertIn('error',records['routed-drc.rpt']['reopened'])
            with self.assertRaises(ValueError): replay.compare_reports(a,a)

    def test_tcl_replays_the_same_commands_before_supplemental_queries(self):
        tcl = (SCRIPTS/'inspect-mega-postroute.tcl').read_text()
        commands = re.findall(r'^([^\n]+) -file \[file join \$replay ([\w.-]+)\]$',tcl,re.M)
        self.assertEqual(commands, [(cmd,name) for name,cmd in replay.COMMANDS.items()])
        self.assertLess(tcl.rindex('[file join $replay '),tcl.index('report_exceptions $option'))
