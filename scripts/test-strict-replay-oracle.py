#!/usr/bin/env python3
"""Negative control: alter one expected heap byte only; exact PCs alone must not pass."""
import argparse
from hashlib import sha256
from pathlib import Path
import re
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('model_run', type=Path); p.add_argument('guest', type=Path)
p.add_argument('nm'); p.add_argument('fresh_dir', type=Path); a = p.parse_args()
out = a.fresh_dir.resolve(); out.mkdir(mode=0o700)
guest = a.guest.resolve()/'performance'; orig = guest/'replay'; run = a.model_run.resolve()
symbols = subprocess.check_output([a.nm,'-n',orig/'entry.elf'],text=True)
hits = re.findall(r'(?m)^([0-9a-f]+) r exp_heap$',symbols)
if len(hits) != 1: raise ValueError('missing or ambiguous private oracle location')
offset = int(hits[0],16)-0x80000000; mem = bytearray((orig/'mem.bin').read_bytes())
expected = (guest/'out-heap').read_bytes()
if not 0 < offset < 65536-2000 or len(expected)!=2000 or mem[offset:offset+2000]!=expected:
    raise ValueError('refusing to modify anything outside expected-heap bytes')
mem[offset] ^= 1; bad=out/'negative.bin'; bad.write_bytes(mem)
with (out/'negative.uart').open('wb') as uart, (out/'negative.events').open('wb') as events:
    res = subprocess.run([run/'model',bad,orig/'prefix.frame','1347261',out/'negative.pc'],
                         stdout=uart, stderr=events, timeout=1200)
trace_hash = sha256((out/'negative.pc').read_bytes()).hexdigest()
if (res.returncode != 1 or (out/'negative.uart').read_bytes()!=b'UART5_READY v1\r\nUART5_HANDOFF\r\n!' or
    (out/'negative.events').read_bytes()!=(run/'performance.events').read_bytes()+b'REPLAY_FAIL user state, fences or count mismatch\n' or
    trace_hash!='416ac8d959c93fdc7b2c57778b2bfe53488c3b105901127d226f5a3c0fc564c4'):
    raise ValueError('negative replay did not fail for the expected independent state check')
print('EXPECTED_HEAP_FAULT_REJECTED_WITH_UNCHANGED_USER_TRACE')
