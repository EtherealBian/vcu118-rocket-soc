import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1] / 'scripts/review-mig-gray.py'
spec=importlib.util.spec_from_file_location('gray',path); g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

def fixture():
    bits='channel\tpointer\tbit\tlaunch_clock\tcapture_clock\tlaunch\tcapture\n'; delays='channel\tpointer\tbit\tcorner\tdata_ns\tlogic_levels\n'; report='| Design State : Physopt postRoute |\n'
    for n,(ch,p) in enumerate(sorted(g.GROUPS)):
        forward=(ch in ('aw','ar','w'))==(p=='widx'); iface=('nodeOut_' if ch in ('aw','ar','w') else 'nodeIn_')+ch
        bases=('mig/axi4asource','mig/island/axi4asink'); src,dst=bases if forward else bases[::-1]; ec=(g.SYS,g.UI) if forward else (g.UI,g.SYS); pairs=[]
        for i in range(4):
            l=f'{src}/{iface}_'+('source/' if p=='widx' else 'sink/')+f'{p}_gray_reg[{i}]'; r=f'{dst}/{iface}_'+('sink/' if p=='widx' else 'source/')+f'{p}_{p}_gray/output_chain'+(f'_{i}' if i else '')+'/sync_2_reg'; pairs.append((l,r))
            bits+='\t'.join((ch,p,str(i),*ec,l,r))+'\n'
            for c,v in [('min','0.2'),('max','0.6')]: delays+='\t'.join((ch,p,str(i),c,v,'0'))+'\n'
        report+=f'Id: {n+1}\nset_bus_skew -from '+ ' '.join(x for x,_ in pairs)+' -to '+' '.join(x for _,x in pairs)+' 5.000\nEndpoints: 4\n'
        for i,(l,r) in enumerate(pairs):
            a,b=pairs[(i+1)%4];report+=f'Slack (MET) : 4.800ns\n  Endpoint Source: {l}/C\n  Endpoint Destination: {r}/D\n  Reference Source: {a}/C\n  Reference Destination: {b}/D\n  Actual Bus Skew: 0.200ns\n'
    return bits,delays,report

class GrayTest(unittest.TestCase):
    def test_all_40_bits_with_80_corner_values(self):
        b,d,r=fixture(); result=g.analyze(b,d,r.replace('\n','\r\n'));self.assertEqual(len(result),10); self.assertEqual(result['ar:ridx']['minimum_reported_skew_slack_ns'],4.8)
    def test_routed_requires_explicit_exact_state(self):
        b,d,r=fixture(); r=r.replace('Physopt postRoute |','Routed')
        with self.assertRaises(ValueError): g.analyze(b,d,r)
        self.assertEqual(len(g.analyze(b,d,r,'Routed')),10)
        for bad in (r.replace('Routed','Routed example'),r+'| Design State : Routed\n'):
            with self.assertRaises(ValueError): g.analyze(b,d,bad,'Routed')
    def test_corruption_not_characterized(self):
        b,d,r=fixture()
        for bad in [(b.replace('chain_1','chain_2',1),d,r),(b,d.replace('\tmin\t','\tmax\t',1),r),(b,d.replace('0.6','nan',1),r),(b,d.replace('0.2','0.9',1),r),(b,d,r.replace('Endpoints: 4','Endpoints: 3',1)),(b,d,r.replace('Actual Bus Skew: 0.200','Actual Bus Skew: 1.200',1)),(b,d,r.replace('sync_2_reg/D','sync_1_reg/D',1)),(b,d,r[:r.rindex('Id:')]),(b,d,r.replace('Physopt postRoute','Synth Design'))]:
            with self.assertRaises(ValueError): g.analyze(*bad)
if __name__=='__main__': unittest.main()
