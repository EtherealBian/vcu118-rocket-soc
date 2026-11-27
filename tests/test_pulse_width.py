from decimal import Decimal
from pathlib import Path
import re
import runpy
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
pw = runpy.run_path(str(SCRIPTS/'review-pulse-width.py'))
P, C, T = pw['PULSE'], pw['CLOCKS'], pw['TIMING']
CPU = pw['CPU']


def header(path, cmd):
    bar = '-'*24+'\n'
    fields = [('Tool Version','Vivado v.2024.2 test'), ('Date','date'),('Host','test'),
              ('Command',cmd+' -file '+path.resolve().as_posix()), ('Design','VCU118FPGATestHarness'),
              ('Device','xcvu9p-flga2104'), ('Speed File','test'), ('Design State','Physopt postRoute')]
    return bar+''.join('| '+k+' : '+v+'\n' for k,v in fields)+bar


class PulseReview(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.dir = Path(tmp.name)
        sections, groups, clocks, intra = [], [], [], []
        bar = '-'*22+'\n'
        # All have 5 endpoints; CPU has the only failing endpoint. Skew has signed inputs.
        for name in sorted(pw['DOMAINS']):
            src = name+'/clk'; pin = name+'/FF/C'
            if name.endswith('_DIV'): src += ' '+name+'/second'
            clk = [f'Clock Name:  {name}', 'Waveform(ns):  { 0.000 5.000 }', 'Period(ns):  10.000',
                   f'Sources:  {{ {src} }}','', '  '.join(pw['COLUMNS'])]
            def row(kind,req,act,slack,corner='Slow',ref='n/a'):
                return '  '.join([kind,corner,'FF/C',ref,req,act,slack,'SITE1',pin])
            clk.append(row('Min Period','3.000','10.000','7.000','n/a'))
            if name in ('mmcm_clkout0','sys_clock'): clk.append(row('Max Period','11.000','10.000','1.000','n/a'))
            fail = int(name == CPU); w = '-0.100' if fail else '1.000'; t = '-0.100' if fail else '0.000'
            clk += [row('Low Pulse Width','5.100' if fail else '4.000','5.000',w),row('High Pulse Width','4.000','5.000','1.000')]
            if name == 'mmcm_clkout6' or re.fullmatch(r'pll_clk\[\d\]',name):
                clk.append(row('Max Skew','-0.250','-1.500','1.250','Fast','FF/D'))
            block = '\n'.join(clk); sections.append(block)
            groups.append(f'From Clock:  {name}\n  To Clock:  {name}\nPW    :  {fail}  Failing Endpoints,  Worst Slack  {w}ns,  Total Violation  {t}ns\n'+bar+'\nPulse Width Checks\n'+bar+block+'\n\n'+bar)
            clocks.append(f'{name}  10.000  {{0.000 5.000}}  P  {{{src}}}')
            intra.append((name,w,t,fail))
        h1 = 'WNS(ns)  TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints  WHS(ns)  THS(ns)  THS Failing Endpoints  THS Total Endpoints'
        h2 = '  WPWS(ns)  TPWS(ns)  TPWS Failing Endpoints  TPWS Total Endpoints'
        it = 'Clock'.ljust(110)+h1
        self.bodies = {
            P:'Pulse Width Report\n\n'+'\n\n'.join(sections),
            C:'Clock  Period(ns)  Waveform(ns)  Attributes  Sources\n'+'\n'.join(clocks)+'\n\n================\n',
            T:'Report\n| Design Timing Summary\n'+h1+h2+'\n------\n1.000 0.000 0 10 1.000 0.000 0 10 -0.100 -0.100 1 65\n| Clock Summary\n| Intra Clock Table\n'+it+h2+'\n-------\n'+
              '\n'.join(n.ljust(len(it))+f' {w} {t} {bad} 5' for n,w,t,bad in intra)+'\n| Inter Clock Table\n'+'\n'.join(groups)}
        self.raw = {n:header(self.dir/n,cmd)+self.bodies[n] for n,cmd in [(P,'report_pulse_width'),(C,'report_clocks'),(T,'report_timing_summary -report_unconstrained')]}
        for n,s in self.raw.items(): self.write(n,s)

    def write(self,n,s):
        (self.dir/n).write_bytes((s+'\n').encode())

    def test_negative_slack_and_signed_max_skew_are_retained(self):
        r,_,pulse = pw['audit'](self.dir)
        self.assertEqual((r['failing'],r['endpoints'],r['wpws_ns']), (1,65,'-0.100'))
        self.assertEqual(r['clocks'][CPU]['representative_min_checks'],['Low Pulse Width'])
        self.assertEqual(r['clocks']['pll_clk[2]_DIV']['source_count'],2)
        self.assertEqual(sum(len(v[1]) for v in pulse.values()),45)
        # A reopened embedded report must match the original representative at the physical pin.
        self.write(T,self.raw[T].replace('SITE1','SITE2',1))
        with self.assertRaisesRegex(ValueError,'embedded pulse details differ'): pw['audit'](self.dir,pulse)

    def test_native_report_mutations(self):
        n = 'pll_clk[1]_DIV'
        for name,old,new in [(P,'Physopt postRoute','Routed'),(P,'report_pulse_width -file','report_pulse_width -foo -file'),
                (P,'Speed File : test','Speed File : other'),(P,(self.dir/P).as_posix(),(self.dir/'other.rpt').as_posix()),
                (P,'SITE1','SITE2'), (P,'3.000  10.000  7.000','3.000  10.000  7.002'),
                (P,'-0.250  -1.500  1.250','-0.250  -1.500  -1.250'),(P,'11.000  10.000  1.000','11.000  10.000  -1.000'),
                (P,'Clock Name:  '+n,'Clock Name:  pll_clk[0]_DIV'), (P,'Low Pulse Width','High Pulse Width'),
                (C,n+'/second',n+'/third'),(C,'{0.000 5.000}','{0.000 4.999}'),
                (T,'Total Violation  -0.100ns','Total Violation  0.000ns'), (T,'To Clock:  JTCK','To Clock:  '+CPU),
                (T,'1 65','1 66'),(T,'-0.100 -0.100 1 65','-0.099 -0.100 1 65')]:
            with self.subTest(name=name,old=old):
                self.assertIn(old,self.raw[name]); self.write(name,self.raw[name].replace(old,new,1))
                with self.assertRaises(ValueError): pw['audit'](self.dir)
                self.write(name,self.raw[name])

    def test_consistently_truncated_or_wrong_domain_is_not_summary_agreement(self):
        # Keep both pulse listings identical and leave the entire timing summary unchanged.
        for pattern,replacement in [(r'^Min Period[^\n]+\n',''),
                                    (r'Low Pulse Width  Slow  FF/C  n/a  5.100  5.000  -0.100','Low Pulse Width  Slow  FF/C  n/a  4.000  5.000  1.000')]:
            with self.subTest(pattern=pattern):
                for name in (P,T): self.write(name,re.sub(pattern,replacement,self.raw[name],flags=re.M))
                with self.assertRaises(ValueError): pw['audit'](self.dir)

    def test_only_documented_archival_discrepancy_is_reportable(self):
        # The old 1 ps representative/summary difference must never exempt a new route.
        name='pll_clk[2]'; spec=('0.625','0.000','0.312',('clk',)); rows=[('High Pulse Width',0,0,0,0,0,'0.144')]
        args=({name:(spec,rows)},{name:spec},{name:(Decimal('.143'),Decimal('0'),0,1)},(Decimal('.143'),Decimal('0'),0,1))
        with self.assertRaises(ValueError): pw['crosscheck'](*args)
        r=pw['crosscheck'](*args,archived_rounding=True)['clocks'][name]
        self.assertEqual((r['wpws_ns'],r['representative_min_ns']),('0.143','0.144'))
