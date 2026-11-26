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
        for i,profile in enumerate(m.ORDER,1):
            elf=profile.encode();path,flags=m.cm.PROFILES[profile];(self.d/(Path(path).name+'.elf')).write_bytes(elf);d=self.d/f'{i:02}-{profile}';d.mkdir();n=f'{i:014x}'
            raw=(f.fixture().decode().replace(f.nonce,n).replace(f.elf+'  /bin/coremark',f'CM_SESSION_{self.tag}_42_{n}\r\n'+h(elf)+'  '+path).replace(m.cm.FLAGS,flags).replace(': 6000',': 12000').replace('300.000000','600.000000')).encode()
            if profile=='o3-zb':raw=raw.replace(h(elf).encode(),f'isa : rv64imafdc_zba_zbb\r\nCM_ISA_END_42_{n}\r\n{h(elf)}'.encode(),1)
            (d/'uart.txt').write_bytes(raw);(d/'nonce.txt').write_text(n);t=dict(performance=20100,validation=20100);(d/'host-ms.json').write_text(json.dumps(t));result=m.cm.inspect(raw,n,h(elf),12000,t,profile);result['boot']={k:v for k,v in self.boot.items() if k not in ('volatile_configuration','shell_challenge_verified')};result['iterations_requested']=12000;(d/'result.json').write_text(json.dumps(result))
    def test_balanced_and_not_target(self):
        r=m.review(self.boot,self.d,self.d);self.assertFalse(r['profiles']['o3']['all_three_at_least_1000']);self.assertEqual(len(r['profiles']['o3-zb']['measurements']),3)
    def test_reject_missing_session_and_wrong_bit(self):
        with self.assertRaises(ValueError):m.review(dict(self.boot,bit_sha256='1'*64),self.d,self.d)
        p=self.d/'03-o3-zb/uart.txt';p.write_bytes(p.read_bytes().replace(b'CM_SESSION_',b'OTHER_'))
        with self.assertRaises(ValueError):m.review(self.boot,self.d,self.d)
    def test_reject_modified_aggregate_input(self):
        p=self.d/'02-o3/result.json';r=json.loads(p.read_text());r['runs']['performance']['iterations_per_s']='1200';p.write_text(json.dumps(r))
        with self.assertRaises(ValueError):m.review(self.boot,self.d,self.d)
