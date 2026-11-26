#!/usr/bin/env python3
"""Verify six short, debug-preloaded M-mode RTL windows. No score is generated."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from cpu_window_report import windows, START, END

MODEL = re.compile(r'CPU_WINDOW_MODEL_PASS mode=debug-cpu-window cycles=(\d+) sectors_started=0 tl_read_transactions=(\d+) tl_write_transactions=(\d+) \(behavioral RAM/card, no physical DDR\)')


def decode(text):
    # The real board ROM may start printing before the simulated JTAG halt.
    prefix, sep, tail = text.partition(START)
    if not sep or 'CPUWIN' in prefix or START in tail or 'CPUWIN_FAIL' in text:
        raise ValueError('invalid diagnostic epoch')
    lines = (START + tail).splitlines()
    if len(lines) != 10 or lines[7:9] != [END, ''] or not (end := MODEL.fullmatch(lines[9])):
        raise ValueError('incomplete diagnostic or model report')
    results = windows(lines[:8])
    total, rd, wr = map(int, end.groups())
    if not sum(r['cycles'] for group in results.values() for r in group['samples']) < total <= 40000000 or rd == 0:
        raise ValueError('impossible model transaction count or time budget')
    # Dirty data can remain in a write-back cache; zero backing-RAM writes is valid.
    return dict(**results, model_cycles=total, backing_reads=rd, backing_writes=wr)


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def review(out, kit, diag, harness):
    files = [out/'sim', kit/'CANDIDATE.sha256', diag/'window.bin', diag/'window.elf', kit/'rom/sdboot.elf', harness]
    lines = (out/'inputs.sha256').read_text().splitlines()
    if len(lines) != len(files): raise ValueError('missing provenance')
    hashes = {}
    for line, file in zip(lines, files):
        h, name = line.split('  ', 1)
        if Path(name).name != file.name or digest(file) != h: raise ValueError('model input changed: '+file.name)
        hashes[file.name] = h
    text = (out/'console.txt').read_text(encoding='ascii')
    err = (out/'simulator.txt').read_text(encoding='ascii')
    if len(re.findall(r'^JTAG_PRELOADED_HANDOFF entry=0x80000000 dtb=0x1[0-9a-f]{4} \(not SD handoff\)$',err,re.M)) != 1 or 'RTL TEST FAIL' in err:
        raise ValueError('missing verified debug handoff')
    return dict(scope='Functional ChipTop RTL, behavioral memory, debug-preloaded, bare-metal; not a board or Linux CoreMark score.',
                inputs=hashes, console_sha256=digest(out/'console.txt'), **decode(text))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('out', 'kit', 'diag'):p.add_argument(arg, type=Path)
    x = p.parse_args(); print(json.dumps(review(x.out, x.kit, x.diag, Path(__file__).resolve().parents[1]/'tests/rocket_chiptop.cpp'),indent=2))
