import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from uart_frame import encode, MAX_BYTES

class WireFrameTests(unittest.TestCase):
    def test_wire_and_standard_crc_vector(self):
        self.assertEqual(encode(b'123456789'), b'VCU118U5\x09\0\0\0\x26\x39\xf4\xcb123456789')

    def test_minimum_and_maximum(self):
        self.assertEqual(len(encode(b'x')),17)
        self.assertEqual(len(encode(bytes(MAX_BYTES))),16+MAX_BYTES)
        for data in (b'', bytes(MAX_BYTES+1)):
            with self.assertRaises(ValueError): encode(data)

    def test_cli_digest_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; f=Path(d)/'f'; p.write_bytes(bytes(range(256)))
            cmd=[sys.executable,str(SCRIPTS/'uart_frame.py'),str(p),str(f)]
            m=json.loads(subprocess.check_output(cmd))
            self.assertEqual(m['frame_sha256'], hashlib.sha256(f.read_bytes()).hexdigest())
            self.assertEqual(m['payload_sha256'], hashlib.sha256(p.read_bytes()).hexdigest())
            p.write_bytes(b'x')
            self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)
            self.assertEqual(m['frame_sha256'], hashlib.sha256(f.read_bytes()).hexdigest())
