import hashlib
import importlib.util
import sys
import unittest
import zlib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


packed = load('verify-packed-boot')
link = load('review-linux-serial')


class PackedTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.block, self.stage = b'ABC', b'\x30ABC', b'HEAD\x30ABC'
        sha = lambda b: hashlib.sha256(b).hexdigest()
        crc = '%08x' % zlib.crc32(self.raw)
        self.meta = dict(raw_bytes=3, raw_sha256=sha(self.raw), raw_crc32=crc,
                         block_bytes=4, block_sha256=sha(self.block), stage_bytes=8,
                         stage_sha256=sha(self.stage), wire_bytes_saved=-5,
                         stage_copy_address='0x84000000', output_address='0x80000000', stage_stack='0x87fff000')
        self.ok = 'UART5_PACK1_OK bytes=3 crc32='+crc
        self.lines = ['UART5_READY v1', 'UART5_HANDOFF', self.ok, 'firmware']

    def check(self, lines, meta):
        return packed.inspect(self.raw, self.stage, self.block, meta, ('\r\n'.join(lines)+'\r\n').encode())

    def test_binding(self):
        self.assertEqual(self.check(self.lines, self.meta), self.meta)
        for key in self.meta:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(self.lines, dict(self.meta, **{key: None}))

    def test_reject_crc_markers(self):
        for rows in (self.lines[:2] + self.lines[3:], self.lines + [self.ok],
                     self.lines[:2] + ['UART5_PACK1_STOP'], self.lines[:1]+[self.ok]+self.lines[1:2],
                     self.lines[:2]+['UART5_PACK1_OK bytes=3 crc32=00000000'], self.lines + ['UART5_PACK1_STOP']):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.check(rows, self.meta)

    def test_compare_requires_matched_boot(self):
        r = dict(bit_sha256='b'*64, mode='linux', payload_sha256=self.meta['raw_sha256'],
                 shell_challenge_verified=True, host_elapsed_ms={'rom_handoff':190,'shell_prompt':199,'accept':200})
        p = dict(r, packed_stage=self.meta, payload_sha256=self.meta['stage_sha256'],
                 host_elapsed_ms={'rom_handoff':80,'shell_prompt':90,'accept':100})
        self.assertEqual(packed.compare(r,p)['milliseconds_saved_to_shell_response'],100)
        for k,v in (('mode','linux-oscheck'),('bit_sha256','a'*64),('payload_sha256','e'*64),('shell_challenge_verified',False)):
            with self.subTest(k=k), self.assertRaises(ValueError):
                packed.compare(dict(r, **{k:v}),p)
        for a in (None,{},dict(rom_handoff=100,shell_prompt=90,accept=120)):
            with self.assertRaises(ValueError): packed.compare(dict(r,host_elapsed_ms=a),p)


class SerialTests(unittest.TestCase):
    def setUp(self):
        self.n = '0123456789abcd'
        self.v = [('%0256x' % i) for i in range(32)]
        row = lambda n: '  9: %8d SiFive PLIC  1 Edge   64000000.serial' % n
        rows = ['# LINK_LIVE_42_'+self.n, 'LINK_BEGIN_42_'+self.n, row(20), 'LINK_READY_'+self.n]
        for i,s in enumerate(self.v,1):
            rows.extend([s,hashlib.sha256((s+'\n').encode()).hexdigest()+'  -','LINK_ACK_%d_%s' % (i,self.n)])
        self.rows = rows + ['LINK_AFTER_'+self.n, row(30), 'LINK_END_42_'+self.n]

    def inspect(self, rows, v=None, nonce=None):
        return link.inspect(('\r\n'.join(rows)+'\r\n').encode(), self.v if v is None else v, nonce or self.n)

    def test_positive(self):
        s=self.inspect(self.rows)
        self.assertEqual((s['records'],s['ascii_payload_bytes'],s['plic_serial_delta']),(32,8192,10))

    def test_explain_interrupted_record_but_never_accept_it(self):
        diagnose=load('diagnose-linux-serial');rows=self.rows.copy();original=self.v[26];idx=4+26*3
        shortened=original[:74]+original[97:]
        rows[idx:idx+2]=[original[:74]+'[   36.100000] random: crng init done',original[97:],hashlib.sha256((shortened+'\n').encode()).hexdigest()+'  -']
        with self.assertRaises(ValueError):self.inspect(rows)
        encode=lambda r:('\r\n'.join(r)+'\r\n').encode()
        r=diagnose.explain(encode(rows),self.v,self.n);x=r['affected'][0]
        self.assertEqual((x['record'],x['echo_chars'],x['timestamped_kernel_lines']),(27,233,1));self.assertFalse(x['guest_digest_matches_full_line']);self.assertTrue(x['guest_digest_matches_reconstructed_echo'])
        with self.assertRaises(ValueError):diagnose.explain(encode(self.rows),self.v,self.n)
    def test_echo_hash_ack_and_boundary(self):
        for i,bad in ((4,self.v[1]),(5,'e'*64+'  -'),(6,'LINK_ACK_2_'+self.n),(2,'none'),(-2,self.rows[2]),(-1,'# stale')):
            rows=self.rows.copy();rows[i]=bad
            with self.subTest(i=i), self.assertRaises(ValueError):self.inspect(rows)
        with self.assertRaises(ValueError):self.inspect(self.rows[:-2]+[self.rows[-2]]+self.rows[-2:])
        with self.assertRaises(ValueError):self.inspect(self.rows,nonce='f'*14)
        with self.assertRaises(ValueError):self.inspect(self.rows,v=[self.v[0]]*32)
        with self.assertRaises(ValueError):link.command('not a nonce')
