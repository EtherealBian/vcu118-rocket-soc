#!/usr/bin/env python3
"""Verify six short, debug-preloaded M-mode RTL windows. No score is generated."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from statistics import median

from cpu_window_report import windows, START, END

MODEL = re.compile(r'CPU_WINDOW_MODEL_PASS mode=debug-cpu-window cycles=(\d+) sectors_started=0 tl_read_transactions=(\d+) tl_write_transactions=(\d+) \(behavioral RAM/card, no physical DDR\)')


EVENTS = ('br_misp','jalr_misp','flush','ic_acq','dc_acq')
EVENT_LINE = re.compile(r'BOOM_HPM seed=(\d+) sample=(\d+)' + ''.join(' '+k+r'=(\d+)' for k in EVENTS))

def decode(text, boom_events=False):
    # The real board ROM may start printing before the simulated JTAG halt.
    prefix, sep, tail = text.partition(START)
    if not sep or 'CPUWIN' in prefix or START in tail or 'CPUWIN_FAIL' in text:
        raise ValueError('invalid diagnostic epoch')
    lines = (START + tail).splitlines()
    observed = []
    if boom_events:
        if 'BOOM_HPM' in prefix or len(lines) != 16: raise ValueError('incomplete BOOM event capture')
        for i, row in enumerate(lines[1:13:2]):
            hit = EVENT_LINE.fullmatch(row)
            if not hit: raise ValueError('BOOM event row absent or malformed')
            k, j, *counts = map(int, hit.groups())
            if (k,j) != ((0,0x3415)[i%2],i//2): raise ValueError('BOOM event window order')
            observed.append(dict(zip(EVENTS,counts)))
        lines = lines[:1] + lines[2:13:2] + lines[13:]
    if len(lines) != 10 or lines[7:9] != [END, ''] or not (end := MODEL.fullmatch(lines[9])):
        raise ValueError('incomplete diagnostic or model report')
    results = windows(lines[:8])
    total, rd, wr = map(int, end.groups())
    if not sum(r['cycles'] for group in results.values() for r in group['samples']) < total <= 40000000 or rd == 0:
        raise ValueError('impossible model transaction count or time budget')
    if boom_events:
        for group, events in zip(('performance_seed','validation_seed'),(observed[::2],observed[1::2])):
            samples = results[group]['samples']
            for row, cnt in zip(samples,events):
                if any(n > total for n in cnt.values()): raise ValueError('impossible BOOM event count')
                row['event_cycles'] = cnt
            results[group]['median_event_cycles_per_1000_retired'] = {
                k: round(median(r['event_cycles'][k]*1000/r['retired'] for r in samples),6) for k in EVENTS}
        results['event_scope'] = 'BOOM v3 Medium M-mode, five selector readbacks, event-bearing cycles around iterate(); not a branch miss rate or a decomposition of stall cycles.'
    # Dirty data can remain in a write-back cache; zero backing-RAM writes is valid.
    return dict(**results, model_cycles=total, backing_reads=rd, backing_writes=wr)


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def review(out, kit, diag, harness, boom_events=False):
    files = [out/'sim', kit/'CANDIDATE.sha256', diag/'window.bin', diag/'window.elf', kit/'rom/sdboot.elf', harness]
    lines = (out/'inputs.sha256').read_text().splitlines()
    if len(lines) != len(files): raise ValueError('missing provenance')
    hashes = {}
    for line, file in zip(lines, files):
        h, name = line.split('  ', 1)
        if Path(name).name != file.name or digest(file) != h: raise ValueError('model input changed: '+file.name)
        hashes[file.name] = h
    if boom_events:
        config=kit/'config.scala'
        if (config.read_bytes() != (Path(__file__).resolve().parents[1]/'rtl/perf/PerfMediumBoom.scala').read_bytes()
            or digest(config)+'  config.scala' not in (kit/'CANDIDATE.sha256').read_text().splitlines()
            or '-DVCU_BOOM_EVENTS=1' not in (diag/'build-flags.txt').read_text().splitlines()):
            raise ValueError('instrumented Medium BOOM inputs required')
    text = (out/'console.txt').read_text(encoding='ascii')
    err = (out/'simulator.txt').read_text(encoding='ascii')
    if len(re.findall(r'^JTAG_PRELOADED_HANDOFF entry=0x80000000 dtb=0x1[0-9a-f]{4} \(not SD handoff\)$',err,re.M)) != 1 or 'RTL TEST FAIL' in err:
        raise ValueError('missing verified debug handoff')
    return dict(scope='Functional ChipTop RTL, behavioral memory, debug-preloaded, bare-metal; not a board or Linux CoreMark score.',
                inputs=hashes, console_sha256=digest(out/'console.txt'), **decode(text,boom_events))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('out', 'kit', 'diag'):p.add_argument(arg, type=Path)
    p.add_argument('--boom-events',action='store_true')
    x = p.parse_args(); print(json.dumps(review(x.out, x.kit, x.diag, Path(__file__).resolve().parents[1]/'tests/rocket_chiptop.cpp',x.boom_events),indent=2))
