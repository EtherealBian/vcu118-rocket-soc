import importlib.util
import tempfile
import unittest
from pathlib import Path

script = Path(__file__).resolve().parents[1] / 'scripts/symbolize-linux-profile.py'
spec = importlib.util.spec_from_file_location('linux_profile', script)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class ProfileTests(unittest.TestCase):
    fields = ['csr' + t for t in ('7b1', '7b0', '180', '142', '141', '143', '342', '341', '343')] + ['x1', 'x2', 'x10', 'x11']

    def record(self, fields, suffix=' resumed'):
        return 'LINUX_JTAG_SAMPLE cycle=19 ' + ' '.join(k + '=0x0' for k in fields) + suffix

    def test_complete_and_partial(self):
        self.assertEqual(list(profile.samples(self.record(self.fields))), [(19, dict.fromkeys(self.fields, 0))])
        self.assertEqual(list(profile.samples(self.record(self.fields, ''))), [])

    def test_reject_wrong_field_set_and_bad_values(self):
        for row in (self.record(self.fields[:-1]), self.record(self.fields + ['x1']),
                    self.record(self.fields).replace('csr180=0x0', 'csr180=0x0?')):
            with self.assertRaises(ValueError):
                list(profile.samples(row))

    def test_log_input_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            fw = Path(folder) / 'fw'; fw.write_bytes(b'firmware')
            lines = [profile.sha(fw) + '  fw', '0' * 64 + '  disk', '1' * 64 + '  sim']
            profile.verify_logged_input('\n'.join(lines) + '\nJTAG IDCODE=0x1', fw)
            for rows in ([lines[1], lines[0], lines[2]], lines[:2], lines * 2):
                with self.assertRaises(ValueError):
                    profile.verify_logged_input('\n'.join(rows), fw)
