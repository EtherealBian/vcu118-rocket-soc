"""Exercise source attribution independently of an FPGA installation."""
from pathlib import Path
import runpy
import unittest

F = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-mega-recovery-synthesis.py'))


class Lineage(unittest.TestCase):
    def test_require_completions_from_same_source_and_language(self):
        ids={'/new/x.sv': ('kit/x.sv',None), '/new/y.vhd': ('ip/y.vhd',None)}
        v="INFO: [Synth 8-6157] synthesizing module 'example' [/new/x.sv:11]"
        d="INFO: [Synth 8-6155] done synthesizing module 'example' (0#1) [/new/x.sv:11]"
        vh="INFO: [Synth 8-638] synthesizing module 'other' [/new/y.vhd:19]"
        vd="INFO: [Synth 8-256] done synthesizing module 'other' (0#1) [/new/y.vhd:19]"
        text='\n'.join([v,vh,vd,d]); self.assertEqual(len(F['module_rows'](text,ids)),2)
        for corrupted in (text.replace('/new/', '/old/'), text.replace(d,''), text.replace(vd,vd.replace(':19',':20')),
                          text.replace('8-256','8-6155'), text+'\n'+v+'\n'+d, text.replace('8-6157','8-5555')):
            with self.subTest(corrupted=corrupted), self.assertRaises(ValueError): F['module_rows'](corrupted,ids)

    def test_xdc_scope_and_order_must_match(self):
        lines=[]; ids={}
        for n in range(15):
            path=f'/new/{n}.xdc'; ids[path]=(f'ip/{n}.xdc', None)
            start=f"Parsing XDC File [{path}] for cell 'same/expected'"; lines.extend([start,'Finished '+start])
        self.assertEqual(len(F['constraints']('\n'.join(lines),ids)),15)
        for broken in (lines[:-2],lines[:-1]+[lines[-1].replace('expected','other')],lines+lines[:2],
                       [v.replace('/new/3.xdc','/elsewhere/3.xdc') for v in lines]):
            with self.subTest(broken=broken), self.assertRaises(ValueError): F['constraints']('\n'.join(broken),ids)

    def test_only_new_helper_and_three_changed_parents_permitted(self):
        files=['rtl/IssueUnitCollapsing_2.sv','rtl/LoopBranchPredictorBank.sv','rtl/LoopBranchPredictorColumn.sv']
        paths=['kit/'+f for f in files]; lib='tool/'+F['LIB']; ip='ip/example.sv'
        parents=[(Path(k).stem,k,1,'verilog') for k in paths]
        base=[{'project_ip':42},parents,[],{**dict.fromkeys(paths,'a'),lib:'same',ip:'same'},None]
        changed=dict.fromkeys(files,'b'); helper=('VcuIntMissSlot',paths[0],321,'verilog')
        new=[{'project_ip':42},[*parents,helper],[],{**dict.fromkeys(paths,'b'),lib:'same',ip:'same'},None]
        self.assertEqual(F['compare'](base,new,{'changed':changed})['added_module'],helper[0])
        for index,changed_value in ((0,{'project_ip':43}),(1,parents),(1,[*parents,helper,helper]),(3,{**new[3],ip:'drift'}),(2,[('another.xdc',None)])):
            broken=new.copy(); broken[index]=changed_value
            with self.subTest(index=index), self.assertRaises(ValueError): F['compare'](base,broken,{'changed':changed})
