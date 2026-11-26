#!/usr/bin/env python3
"""Cross-check one physical probe recording; output only portable, de-identified evidence."""
import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path


def check_transcript(raw, rounds):
    reader = csv.DictReader(io.StringIO(raw.decode('ascii'), newline=''))
    if reader.fieldnames != ['index', 'request', 'response']:
        raise ValueError('unexpected transcript columns')
    count = 0
    for count, row in enumerate(reader, start=1):
        index = count - 1
        if (None in row or row['index'] != str(index) or
                not re.fullmatch('[0-9a-fA-F]{2}', row['request']) or
                not re.fullmatch('[0-9a-fA-F]{8}', row['response'])):
            raise ValueError(f'invalid row at index {index}')
        req = int(row['request'], 16)
        # Bit permutation expressed differently from either FPGA or host sender.
        bits = f'{req:08b}'
        transformed = int(bits[3:] + bits[:3], 2) ^ 0xa7
        if bytes.fromhex(row['response']) != bytes((ord('V'), ord('1'), index % 256, transformed)):
            raise ValueError(f'bad reply at index {index}')
    if count != rounds or not 8 <= count <= 4096:
        raise ValueError(f'wrong challenge count {count}, expected {rounds}')
    return hashlib.sha256(raw).hexdigest()


def public_record(impl, capture):
    info = json.loads((capture / 'pass.json').read_text(encoding='utf-8-sig'))
    review = json.loads((capture / 'review.json').read_text(encoding='utf-8-sig'))
    build = json.loads((impl / 'build-evidence.json').read_text(encoding='utf-8-sig'))
    if review['design'] != 'vcu118_probe' or info['design'] != review['design'] or info['cpu_or_ddr_test'] is not False:
        raise ValueError('incorrect design or scope')
    bit = hashlib.sha256((impl / 'impl/probe.bit').read_bytes()).hexdigest()
    if not bit == build['bit_sha256'] == info['bit_sha256'] == review['bit_sha256']:
        raise ValueError('image identities differ')
    for name, digest in review['reports'].items():
        if not re.fullmatch('[a-z]+', name) or hashlib.sha256((impl/'impl'/(name+'.rpt')).read_bytes()).hexdigest() != digest:
            raise ValueError('report digest mismatch')
    prog = (capture/'program.txt').read_text(encoding='utf-8-sig', errors='strict').splitlines()
    for tag in ('VOLATILE_PROGRAM_START ', 'VOLATILE_PROGRAM_AND_READBACK_PASS'):
        if sum(line.startswith(tag) for line in prog) != 1:
            raise ValueError('missing or repeated configuration marker')
    readbacks = [line for line in prog if line.startswith('PROGRAM_READBACK ')]
    expected = [f'PROGRAM_READBACK REGISTER.CONFIG_STATUS.SLR{i}.{suffix}={value}'
                for i in range(3) for suffix, value in [('BIT[14]_DONE_PIN',1), ('BIT[00]_CRC_ERROR',0)]]
    if readbacks != expected: raise ValueError('missing, repeated or failed SLR readback')
    rounds = info['rounds']; transcript_digest = check_transcript((capture/'challenges.csv').read_bytes(), rounds)
    if transcript_digest != info['transcript_sha256'] or info['reply_bytes'] != rounds*4 or info['uart'] != '115200 8N1':
        raise ValueError('UART evidence mismatch')
    canonical = {}
    for name, digest in build['sources'].items():
        if name not in ('rtl/boardprobe/probe_protocol.sv','rtl/boardprobe/vcu118_probe.sv','rtl/boardprobe/probe.xdc','scripts/build-board-probe.tcl'):
            raise ValueError('unknown source identity')
        source = (impl/'source'/name).read_bytes()
        if hashlib.sha256(source).hexdigest()!=digest: raise ValueError('source changed')
        canonical[name]=hashlib.sha256(source.replace(b'\r\n',b'\n')).hexdigest()
    if len(canonical)!=4: raise ValueError('missing source')
    return dict(design=info['design'], utc=info['utc'], link=info['uart'], rounds=rounds,
                reply_bytes=rounds*4, transcript_sha256=transcript_digest, bit_sha256=bit,
                configuration='volatile JTAG; all three SLRs DONE=1 and CRC_ERROR=0',
                route=review['route'], timing=review['timing'], build_source_sha256=build['sources'], source_lf_sha256=canonical,
                test_scope='independent electrical UART/configuration fixture; no Rocket, DDR, SD or Linux')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('impl',type=Path); p.add_argument('capture',type=Path)
    args=p.parse_args(); print(json.dumps(public_record(args.impl,args.capture),indent=2))
