import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import test_coremark as fixtures

ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/review-coremark-matrix.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class MatrixReview(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);self.d=Path(td.name);self.tag='abcd1234abcd1234';(self.d/'session.txt').write_text(self.tag)
        h=lambda b:hashlib.sha256(b).hexdigest();f=fixtures.BenchmarkTests();self.boot=dict(utc='fixture',mode='linux-oscheck',bit_sha256=m.BIT,volatile_configuration=True,shell_challenge_verified=True,payload_sha256=h(b'fw'),uart_sha256=h(b'boot'))
        p=mock.patch.object(m,'BASE_ELF',h(b'baseline'));p.start();self.addCleanup(p.stop)
        self.write_matrix(m.ORDER)

    def write_matrix(self, order, pinned_finals=False):
        h=lambda b:hashlib.sha256(b).hexdigest(); f=fixtures.BenchmarkTests()
        for i,profile in enumerate(order,1):
            elf=profile.encode();path,flags=m.cm.PROFILES[profile];(self.d/(Path(path).name+'.elf')).write_bytes(elf)
            d=self.d/f'{i:02}-{profile}';d.mkdir(exist_ok=True);n=f'{i:014x}'
            raw=f.fixture().decode().replace(f.nonce,n).replace(f.elf+'  /bin/coremark',f'CM_SESSION_{self.tag}_42_{n}\r\n'+h(elf)+'  '+path).replace(m.cm.FLAGS,flags).replace('GCC13.3.0',m.cm.expected_compiler(profile)).replace(': 6000',': 12000').replace('300.000000','600.000000')
            if pinned_finals: raw=raw.replace('0xbeef','0xd340',1).replace('0xbeef','0xbc68',1)
            if '-zb' in profile:raw=raw.replace(h(elf),f'isa : rv64imafdc_zba_zbb\r\nCM_ISA_END_42_{n}\r\n{h(elf)}',1)
            raw=raw.encode();(d/'uart.txt').write_bytes(raw);(d/'nonce.txt').write_text(n);t=dict(performance=20100,validation=20100);(d/'host-ms.json').write_text(json.dumps(t));result=m.cm.inspect(raw,n,h(elf),12000,t,profile);result['boot']={k:v for k,v in self.boot.items() if k not in ('volatile_configuration','shell_challenge_verified')};result['iterations_requested']=12000;(d/'result.json').write_text(json.dumps(result))

    def test_compiler_matrix_pins_known_final_crcs_and_control_elf(self):
        with mock.patch.object(m,'ZB_ELF',hashlib.sha256(b'o3-zb').hexdigest()):
            self.write_matrix(m.COMPILER_ORDER,True)
            result=m.review(self.boot,self.d,self.d,'compilers')
            self.assertEqual(result['control_profile'],'o3-zb')
            self.assertEqual(result['profiles']['g15-zb-lto']['compiler'],'GCC15.1.0')
            self.assertEqual([r['sequence'] for r in result['profiles']['g15-zb-lto']['measurements']],[2,4,9])
            self.write_matrix(m.COMPILER_ORDER,False)
            with self.assertRaisesRegex(ValueError,'pinned .*CRC'):m.review(self.boot,self.d,self.d,'compilers')
        with self.assertRaisesRegex(ValueError,'ELF identity'):m.review(self.boot,self.d,self.d,'compilers')

    def test_portable_matrix_latin_order_final_crcs_and_all_elf_ids(self):
        ids={p:hashlib.sha256(p.encode()).hexdigest() for p in m.PORTABLE}
        self.write_matrix(m.PORTABLE_ORDER,True)
        with self.assertRaisesRegex(ValueError,'locked portable'):m.review(self.boot,self.d,self.d,'portable')
        with mock.patch.object(m,'PORTABLE_ELFS',ids):
            r=m.review(self.boot,self.d,self.d,'portable')
            self.assertEqual([x['sequence'] for x in r['profiles']['g15-gc-lto']['measurements']],[3,5,7])
            self.assertEqual(r['control_profile'],'baseline')
            self.write_matrix(m.PORTABLE_ORDER,False)
            with self.assertRaisesRegex(ValueError,'pinned .*CRC'):m.review(self.boot,self.d,self.d,'portable')

    def test_tune_matrix_requires_actual_boot_cpu_and_dt_in_each_capture(self):
        digest=lambda data:hashlib.sha256(data).hexdigest()
        ids={p:digest(p.encode()) for p in m.TUNE}
        self.write_matrix(m.TUNE_ORDER,True); boot_nonce='fedc012345abcd'
        def augment(i,p):
            d=self.d/f'{i:02}-{p}';n=(d/'nonce.txt').read_text();file=d/'uart.txt';raw=file.read_bytes();at=ids[p].encode()+b'  /bin/'
            lines=[f'CM_BOOT_{boot_nonce}_42_{n}','0','processor : 0','hart : 0','uarch : sifive,rocket0',
                'b6f54d6d00b160ef946114b90c9f61182f61e2fbc9eef90d11932a2c00633a0a  /sys/firmware/devicetree/base/cpus/timebase-frequency',
                'ead154cbb9f74e30f552dac2f5c6e38890a9a705d9010af7343388daff9d8022  /sys/firmware/devicetree/base/cpus/cpu@0/compatible',
                '547b7dbafa7395a48f9514232ae6e1abfbaff85eafc08413b8276839ff11e28a  /sys/firmware/devicetree/base/soc/pbus_clock/clock-frequency',
                f'CM_MACHINE_END_42_{n}']
            raw=raw.replace(at,('\r\n'.join(lines)+'\r\n').encode()+at); file.write_bytes(raw)
            rec=d/'result.json';obj=json.loads(rec.read_bytes());obj['uart_sha256']=digest(raw);rec.write_text(json.dumps(obj))
        with mock.patch.object(m,'PORTABLE_ELFS',ids),mock.patch.object(m,'TUNED_ELF',ids[m.TUNE[2]]):
            for i,p in enumerate(m.TUNE_ORDER,1):augment(i,p)
            r=m.review(self.boot,self.d,self.d,'tune',boot_nonce)
            self.assertEqual(r['control_profile'],'g15-gc-lto')
            self.assertEqual([x['sequence'] for x in r['profiles'][m.TUNE[2]]['measurements']],[3,5,7])
            with self.assertRaisesRegex(ValueError,'machine marker'):m.review(self.boot,self.d,self.d,'tune','b'*14)
            f=self.d/'03-g15-gc-lto-ooo/uart.txt';orig=f.read_bytes()
            for (old,new,err) in [(b'uarch : sifive,rocket0',b'uarch : ucb-bar,boom0','Rocket CPU'),
                                  (b'0\r\nprocessor',b'0-3\r\nprocessor','Rocket CPU'),
                                  (b'b6f54',b'00f54','live device tree'),
                                  (b'generic-ooo',b'generic-inorder','invalid build')]:
                with self.subTest(old=old),self.assertRaisesRegex(ValueError,err):
                    f.write_bytes(orig.replace(old,new));m.review(self.boot,self.d,self.d,'tune',boot_nonce)
            f.write_bytes(orig)
            with mock.patch.object(m,'TUNED_ELF','0'*64),self.assertRaisesRegex(ValueError,'locked tuning ELFs'):
                m.review(self.boot,self.d,self.d,'tune',boot_nonce)

    def test_balanced_and_not_target(self):
        r=m.review(self.boot,self.d,self.d);self.assertFalse(r['profiles']['o3']['all_three_at_least_1000']);self.assertEqual(len(r['profiles']['o3-zb']['measurements']),3)
    def test_target_uses_all_three_not_the_median_and_still_checks_validation(self):
        from decimal import Decimal
        def rate(seq, ticks):
            d=self.d/f'{seq:02}-o3'; file=d/'uart.txt'; n=(d/'nonce.txt').read_text()
            raw=file.read_bytes(); marker=f'CM_validation_42_{n}'.encode(); before,after=raw.split(marker)
            t=Decimal(ticks)/1000; speed=format(Decimal(12000)/t,'.6f').encode()
            before=before.replace(b'20000',str(ticks).encode()).replace(b'20.000000',format(t,'.6f').encode()).replace(b'600.000000',speed)
            raw=marker.join((before,after)); file.write_bytes(raw); timing={'performance':ticks+100,'validation':20100}
            (d/'host-ms.json').write_text(json.dumps(timing));saved=d/'result.json';rec=json.loads(saved.read_bytes())
            rec.update(m.cm.inspect(raw,n,hashlib.sha256(b'o3').hexdigest(),12000,timing,'o3'));saved.write_text(json.dumps(rec))
        for seq,ticks in [(2,11000),(4,11500),(9,12001)]:rate(seq,ticks)
        stats=m.review(self.boot,self.d,self.d)['profiles']['o3']
        self.assertGreater(Decimal(stats['performance_median']),1000);self.assertFalse(stats['all_three_at_least_1000'])
        self.write_matrix(m.ORDER)
        for seq,ticks in [(2,11000),(4,11500),(9,12000)]:rate(seq,ticks)
        self.assertTrue(m.review(self.boot,self.d,self.d)['profiles']['o3']['all_three_at_least_1000'])
        f=self.d/'09-o3/uart.txt';f.write_bytes(f.read_bytes().replace(b'0xe3c1',b'0xe3c0'))
        with self.assertRaisesRegex(ValueError,'wrong CRC'):m.review(self.boot,self.d,self.d)
    def test_reject_missing_session_and_wrong_bit(self):
        with self.assertRaises(ValueError):m.review(dict(self.boot,bit_sha256='1'*64),self.d,self.d)
        p=self.d/'03-o3-zb/uart.txt';p.write_bytes(p.read_bytes().replace(b'CM_SESSION_',b'OTHER_'))
        with self.assertRaises(ValueError):m.review(self.boot,self.d,self.d)
    def test_reject_modified_aggregate_input(self):
        p=self.d/'02-o3/result.json';r=json.loads(p.read_text());r['runs']['performance']['iterations_per_s']='1200';p.write_text(json.dumps(r))
        with self.assertRaises(ValueError):m.review(self.boot,self.d,self.d)
