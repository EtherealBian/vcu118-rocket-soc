from pathlib import Path
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[1]; spec=importlib.util.spec_from_file_location('paths',ROOT/'scripts/review-mega-routed-paths.py'); p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class MegaRoutedPaths(unittest.TestCase):
    def fixture(self,kind='max'):
        clock=p.CLOCK;path=Path(f'{clock}-{kind}.rpt').resolve(); rows=[{'from':f's{x}/C','to':f'e{x}/D','logic_levels':'7','slack_ns':f'{(x-1)/1000:.3f}'} for x in range(40)]
        text=f'| Command : report_timing -to {clock} -delay_type {kind} -max_paths 8 -nworst 1 -input_pins -file {path.as_posix()}\n| Design State : Physopt postRoute\n| Design : VCU118FPGATestHarness\n| Device : xcvu9p-flga2104\n'
        for i,r in enumerate(rows[:8]):
            edge=f' (rising edge-triggered cell clocked by {clock}  {{rise@0.000ns fall@2.857ns period=5.714ns}})'
            text+=f"Slack ({'MET' if i else 'VIOLATED'}) : {r['slack_ns']}ns\n  Source: {r['from']}\n{edge}\n  Destination: {r['to']}\n{edge}\n  Path Group: {clock}\n  Path Type: {'Setup' if kind=='max' else 'Hold'}\n  Data Path Delay: 4.567ns  (logic 1.567ns (34.3%)  route 3.000ns (65.7%))\n  Logic Levels: 7\n"
        return path,text,rows,kind
    def test_setup_and_hold_even_when_negative(self):
        for kind in ('max','min'):
            r=p.parse_pair(*self.fixture(kind));self.assertEqual((r['sampled_endpoints'],len(r['details']),r['negative_in_sample']),(40,8,1))
    def test_mixed_checkpoint_and_altered_path_rejected(self):
        path,txt,rows,kind=self.fixture()
        for old,new in (('postRoute','postPlace'),('-file ','-file copied/'),('  Destination: e2','  Destination: e9'),('  Source: s0','  Source: s1'),('7\nSlack','9\nSlack'),('VIOLATED','MET'),('0.006ns','0.008ns'),('route 3.000','route 1.000'),('Path Type: Setup','Path Type: Hold')):
            self.assertIn(old,txt)
            with self.subTest(old=old),self.assertRaises(ValueError):p.parse_pair(path,txt.replace(old,new),rows,kind)
    def test_no_duplicate_or_missing_endpoint(self):
        path,txt,rows,kind=self.fixture()
        for bad in (rows[:-1],rows[:-1]+[rows[-2]],list(reversed(rows))):
            with self.assertRaises(ValueError):p.parse_pair(path,txt,bad,kind)
