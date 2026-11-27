import copy
from pathlib import Path
import runpy
import unittest

check = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/compare-mega-regfile-chiptop.py'))


class RegisterFileProbe(unittest.TestCase):
    def test_fault_only_changes_named_immediate(self):
        word = lambda v: v.to_bytes(4,'little')
        a, b = b'head'+word(0x10800313)+b'tail', b'head'+word(0x10900313)+b'tail'
        verify=check['PROBE']['one_immediate'];verify(a,b,4)
        for left,right,offset in [(a,b,0),(a,b,5),(a,b,-4),(a,b,12),(a,a,4),(b,a,4),(a,b+b'!',4),(a,b[:-1],4),(a,b[:-1]+b'X',4)]:
            with self.subTest(offset=offset),self.assertRaises(ValueError):verify(left,right,offset)

    def test_requires_same_controls_and_distinct_models(self):
        def row(role):
            return dict(role=role,kit_seal=role,model_sha256=role,model_archive_sha256=role,rom_dtb_sha256='rom',sources={'h':'fixed'},
                        fixtures={n:dict(elf_sha256=n,payload_sha256=n,frame_sha256=n,frame_bytes=440) for n in ('good','wrong')},
                        wrong_immediate_offset=4,wrong_expected_value_rejected=True,valid=dict(mode='single',cycles=7000000,frame_bytes=440))
        a, b = row('stock'),row('lvt'); same=lambda x,y:check['compare'](x,y,'stock','lvt');same(a,b)
        for key,value in [('role','stock'),('kit_seal','stock'),('model_sha256','stock'),('model_archive_sha256','stock'),('sources',{}),('wrong_immediate_offset',8),('wrong_expected_value_rejected',False),('rom_dtb_sha256','other'),('valid',dict(b['valid'],cycles=99))]:
            with self.subTest(key=key),self.assertRaises(ValueError):same(a,dict(b,**{key:value}))
        x,y=copy.deepcopy(a),copy.deepcopy(b)
        for r in (x,y):r['fixtures']['wrong']['frame_sha256']=r['fixtures']['good']['frame_sha256']
        with self.assertRaises(ValueError):same(x,y)

    def test_archival_program_and_boundary_match_published_results(self):
        from hashlib import sha256
        import json
        root=Path(__file__).resolve().parents[1]
        def validate(file,records):
            record=json.loads((root/'docs'/file).read_bytes())
            for source,hash_field in records.items():
                target=record
                for key in hash_field:target=target[key]
                self.assertEqual(sha256((root/source).read_bytes()).hexdigest(),target,source)
        validate('perf-mega175-regfile-chiptop.json',{
            'software/boot-uart/regfile-probe.S':('sources','assembly'),
            'software/bare/layout.ld':('sources','linker_script'),
            'tests/rom_link.cpp':('sources','pin_harness')})
        validate('perf-mega175-regfile-boundary.json',{'tests/mega_regfile_boundary_tb.v':('bench_sha256',)})
