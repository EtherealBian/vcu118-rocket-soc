from hashlib import sha256
import importlib.util
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'

def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

review = load('review-issue-slice')


class IssueSlice(unittest.TestCase):
    def test_unreviewed_generated_unit_rejected(self):
        with self.assertRaises(ValueError):
            load('issue-ready-fixture').fixtures(b'not the reviewed issue unit')

    def test_matched_inputs_and_completion_not_just_banner(self):
        hashes = {k: sha256(k.encode()).hexdigest() for k in ('stock.sv', 'other.sv', 'wrapper.v', 'driver.cpp')}
        inputs = ['ISSUE_SLICE_INPUT ' + h + ' ' + k for k, h in hashes.items()]
        review.check_miter(inputs + [review.PASS], hashes)
        for bad in (inputs, [review.PASS], inputs[1:] + [review.PASS], inputs[:-1] + [inputs[0], review.PASS],
                    inputs + [review.PASS, review.PASS], inputs + [review.PASS, 'failed'],
                    [inputs[0].replace(hashes['stock.sv'], 'a' * 64)] + inputs[1:] + [review.PASS]):
            with self.assertRaises(ValueError):
                review.check_miter(bad, hashes)

    def test_require_intended_stage_device_and_tool(self):
        header = ('| Design : issue_ref\n| Temperature Grade : E\n| Design State : Routed\n'
                  '| Device : xcvu9p-flga2104\n| Speed File : -2L production\n| Tool Version : Vivado v.2024.2 (test)\n')
        review.check_header(header, 'issue_ref')
        for key in ('issue_ref', '-2L', 'Routed', 'xcvu9p-flga2104', '2024.2'):
            with self.assertRaises(ValueError):
                review.check_header(header.replace(key, 'other'), 'issue_ref')
        with self.assertRaises(ValueError):
            review.check_header(header, 'issue_partial')
