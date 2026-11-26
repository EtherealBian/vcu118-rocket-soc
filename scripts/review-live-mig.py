#!/usr/bin/env python3
"""Summarize the read-only Vivado 2024.2 DDR4 report and independent register property view."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def summarize(report, props):
    def field(name):
        values = re.findall('^' + re.escape(name) + r':[ \t]+([^\r\n]+)$', report, re.M)
        if len(values) != 1: raise ValueError(f'missing/duplicated {name}')
        return values[0].strip()

    def property_value(name):
        values = re.findall('^' + re.escape(name) + r'[ \t]+\S+[ \t]+true[ \t]+(\S+)[ \t]*$', props, re.M)
        if len(values) != 1: raise ValueError(f'missing/duplicated {name}')
        return values[0]

    expected = {'Overall Status':'CAL PASS', 'MicroBlaze Status':'PASS', 'DQS Gate Status':'RUNNING', 'Memory Interface Type':'DDR4', 'Memory Frequency (MHz)':'800', 'Ranks':'1', 'Data Bytes':'8', 'Bits per Byte':'8'}
    if any(field(k) != v for k,v in expected.items()): raise ValueError('calibration or topology differs from reviewed profile')
    required = {'CALIBRATION_FAIL.STATUS':'FALSE', 'CALIBRATION_FAIL.STAGE':'NONE', 'CALIBRATION_FAIL.RANK':'NONE', 'MICROBLAZE_START_UP':'PASS','DQS_GATE_TRACKING':'RUNNING'}
    if any(property_value(k) != v for k,v in required.items()): raise ValueError('calibration property mismatch')
    rows = re.findall(r'^(\d+) - [^:\n]+:\s+(\w+)[ \t]*$', report, re.M)
    prows = re.findall(r'^CAL_STATUS\.RANK0\.(\d+)_\S+\s+string[ \t]+true[ \t]+(\w+)[ \t]*$', props, re.M)
    expected_pass = {1,2,3,4,6,7,8,9,10,11,13,14}
    for group in (rows, prows):
        parsed = [(int(i),status) for i,status in group]
        if sorted(parsed) != [(i,'PASS' if i in expected_pass else 'SKIP') for i in range(1,28)]:
            raise ValueError('missing, duplicated, failed or unexpected rank 0 stage')
    return dict(overall='CAL PASS', microblaze='PASS', dqs_gate_tracking='RUNNING', rank0_stages_passed=len(expected_pass), rank0_stages_skipped=27-len(expected_pass), ranks=1, data_bits=64, reported_memory_clock_mhz=800, active_margin_scan=False)


def record(folder):
    paths = [folder/n for n in ('live-mig.rpt','live-mig-properties.rpt')]
    values = summarize(*(p.read_text(encoding='utf-8-sig') for p in paths))
    values['input_sha256'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return values

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('capture',type=Path); print(json.dumps(record(ap.parse_args().capture),indent=2))
