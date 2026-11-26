import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('capture', Path(__file__).resolve().parents[1]/'scripts/verify-probe-capture.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


class ProbeCaptureTests(unittest.TestCase):
    @staticmethod
    def recording():
        # Fixed vectors deliberately include both bytes that cross the rotate boundary.
        vectors = [(0,0xa7),(1,0xaf),(0x20,0xa6),(0x80,0xa3),(0xff,0x58)]
        h='index,request,response\n'; rows=[]
        for i in range(260):
            req,rsp=vectors[i%len(vectors)]; rows.append(f'{i},{req:02X},5631{i%256:02X}{rsp:02X}\n')
        return (h+''.join(rows)).encode('ascii')

    def test_wrap(self):
        self.assertEqual(len(mod.check_transcript(self.recording(),260)),64)

    def test_corruption(self):
        raw=self.recording()
        for bad in (raw.replace(b'256,01,563100AF',b'256,01,5631FFAF'),raw.replace(b'0,00,563100A7',b'0,00,00000000'),raw.rsplit(b'\n',2)[0],raw+raw.splitlines(True)[-1]):
            with self.subTest(),self.assertRaises(ValueError): mod.check_transcript(bad,260)

    def test_public_record_binds_transcript_not_last_source(self):
        import json, tempfile, hashlib
        d=lambda b:hashlib.sha256(b).hexdigest(); raw=self.recording()
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); run=base/'run'; capture=base/'capture'; capture.mkdir(); (run/'impl').mkdir(parents=True)
            files={}
            for name in ('rtl/boardprobe/probe_protocol.sv','rtl/boardprobe/vcu118_probe.sv','rtl/boardprobe/probe.xdc','scripts/build-board-probe.tcl'):
                path=run/'source'/name; path.parent.mkdir(parents=True,exist_ok=True); payload=(name+'\r\n').encode();path.write_bytes(payload);files[name]=d(payload)
            (run/'impl/probe.bit').write_bytes(b'fixture'); bit=d(b'fixture')
            for path, data in [(run/'build-evidence.json',dict(bit_sha256=bit,sources=files)),(capture/'pass.json',dict(bit_sha256=bit,design='vcu118_probe',rounds=260,reply_bytes=1040,transcript_sha256=d(raw),utc='test',uart='115200 8N1',cpu_or_ddr_test=False)),(capture/'review.json',dict(bit_sha256=bit,design='vcu118_probe',reports={},route={},timing={}))]:
                path.write_text(json.dumps(data))
            (capture/'challenges.csv').write_bytes(raw)
            lines=['VOLATILE_PROGRAM_START test']+[f'PROGRAM_READBACK REGISTER.CONFIG_STATUS.SLR{i}.{kv}' for i in range(3) for kv in ('BIT[14]_DONE_PIN=1','BIT[00]_CRC_ERROR=0')]+['VOLATILE_PROGRAM_AND_READBACK_PASS']
            (capture/'program.txt').write_text('\n'.join(lines))
            self.assertEqual(mod.public_record(run,capture)['transcript_sha256'],d(raw))
            (capture/'program.txt').write_text('\n'.join(lines[:-2]+lines[-1:]))
            with self.assertRaises(ValueError): mod.public_record(run,capture)
