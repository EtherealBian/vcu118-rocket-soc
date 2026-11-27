import hashlib
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'scripts/review-coremark.py'
spec=importlib.util.spec_from_file_location('cm',path);cm=importlib.util.module_from_spec(spec);spec.loader.exec_module(cm)


class BenchmarkTests(unittest.TestCase):
    nonce='012345aabbccff'; elf=hashlib.sha256(b'fixture').hexdigest()
    def fixture(self):
        lines=['CM_LIVE_42_'+self.nonce,self.elf+'  /bin/coremark']
        for kind,(_,seed,lst,mat,state) in cm.CASES.items():
            lines += [f'CM_{kind}_42_{self.nonce}',f'2K {kind} run parameters for coremark.','CoreMark Size : 666','Total ticks : 20000',
                      'Total time (secs): 20.000000','Iterations/Sec : 300.000000','Iterations : 6000','Compiler version : GCC13.3.0',
                      'Compiler flags : '+cm.FLAGS,'seedcrc : '+seed,'[0]crclist : '+lst,'[0]crcmatrix : '+mat,'[0]crcstate : '+state,
                      '[0]crcfinal : 0xbeef','Correct operation validated. See README.md for run and reporting rules.']
            if kind=='performance':lines+=['CoreMark 1.0 : 300.000000 / GCC13.3.0 '+cm.FLAGS+' / Heap']
            lines +=[f'CM_{kind}_RC_0_{self.nonce}']
        return ('\r\n'.join(lines+[f'CM_DONE_42_{self.nonce}'])+'\r\n').encode()
    def test_check_both_runs(self):
        s=cm.inspect(self.fixture(),self.nonce,self.elf,6000,dict(performance=20105,validation=20123));self.assertEqual(s['runs']['performance']['iterations_per_s'],'300.000000')
    def test_host_and_guest_each_need_ten_seconds(self):
        # Synthetic boundary case: unchanged CRCs, consistent guest ticks, rate and summary.
        raw=(self.fixture().replace(b'20000',b'10000').replace(b'20.000000',b'10.000000')
             .replace(b'300.000000',b'600.000000'))
        both=dict(performance=10000,validation=10000)
        result=cm.inspect(raw,self.nonce,self.elf,6000,both)
        self.assertEqual([r['host_observed_ms'] for r in result['runs'].values()],[10000,10000])
        for kind in ('performance','validation'):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError,'host time'):
                cm.inspect(raw,self.nonce,self.elf,6000,{**both,kind:9999})
        short=(raw.replace(b': 10000',b': 9999').replace(b'10.000000',b'9.999000')
               .replace(b'600.000000',b'600.060006'))
        with self.assertRaisesRegex(ValueError,'duration'):
            cm.inspect(short,self.nonce,self.elf,6000,both)
    def test_profiles_bind_flags_and_executable(self):
        for profile,(path,flags) in cm.PROFILES.items():
            data=self.fixture().replace(b'/bin/coremark',path.encode()).replace(cm.FLAGS.encode(),flags.encode()).replace(b'GCC13.3.0',cm.expected_compiler(profile).encode())
            self.assertEqual(cm.inspect(data,self.nonce,self.elf,6000,profile=profile)['profile'],profile)
            self.assertIn('sha256sum '+path+';',cm.command(self.nonce,6000,profile))
            if profile.startswith('g15-'):
                with self.assertRaises(ValueError):cm.inspect(data.replace(b'GCC15.1.0', b'GCC13.3.0'),self.nonce,self.elf,6000,profile=profile)
            if profile!='baseline':
                for change in [(flags.encode(),cm.FLAGS.encode()),(path.encode(),b'/bin/coremark')]:
                    with self.assertRaises(ValueError):cm.inspect(data.replace(*change),self.nonce,self.elf,6000,profile=profile)
        with self.assertRaises(ValueError):cm.command(self.nonce,6000,'baseline; echo oops')
    def test_summary_must_agree_with_build_fields(self):
        data=self.fixture()
        for old,new in [(b'/ GCC13.3.0 ',b'/ GCC99.0 '),(b'-lrt / Heap',b'-lm / Heap'),(b'300.000000 /',b'301.000000 /')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                cm.inspect(data.replace(old,new),self.nonce,self.elf,6000)
    def test_reject_wrong_identity_durations_and_crc(self):
        data=self.fixture()
        for a,b in [(self.elf.encode(),b'0'*64),(b'0xe714',b'0xe3c1'),(b'validation_RC_0',b'validation_RC_1'),(b'20.000000',b'9.999999'),(b'20000',b'19000'),(b': 300.000000',b': 290.000000'),(b'GCC13.3.0',b'other'),(b'/ Heap',b'/ unknown'),(b'CoreMark Size : 666',b'CoreMark Size : 665')]:
            with self.subTest(a=a),self.assertRaises(ValueError):cm.inspect(data.replace(a,b),self.nonce,self.elf,6000)
        with self.assertRaises(ValueError):cm.inspect(data,self.nonce,self.elf,6000,dict(performance=20000,validation=24123))
        with self.assertRaises(ValueError):cm.inspect(data,self.nonce,self.elf,1234)
        with self.assertRaises(ValueError):cm.command('bad',10)
        with self.assertRaises(ValueError):cm.command(self.nonce,-1)
