#!/usr/bin/env python3
"""Recheck a completed private stock Linux RTL run; emit only public fingerprints."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path

from mega_linux_shell_review import ROOT, inspect


def review(run):
    def load(p):
        return json.loads(p.read_bytes())

    def check(ok, why):
        if not ok:
            raise ValueError(why)

    def digest(p):
        return sha256(p.read_bytes()).hexdigest()

    prefix = load(ROOT/'docs/perf-mega175-shell-identity-prefix.json')
    entry = load(ROOT/'docs/perf-mega175-linux-entry.json')
    pins = load(run/'inputs.json')
    check(digest(run/'inputs.json') == prefix['inputs_sha256'], 'wrong run manifest')
    check(digest(run/'model') == pins['model'] == prefix['model_sha256'], 'wrong executable')
    check(digest(run/'nonce') == pins['nonce'], 'wrong challenge file')
    for k in ('fw_payload.bin', 'Image', 'coremark-g15-gc-lto-ooo-strict.elf'):
        check(pins[k] == entry['inputs'][k], 'different release input')
    check(pins['CANDIDATE.sha256'] == prefix['stock_kit_sha256'], 'wrong stock kit')
    u, e = [(run/n).read_bytes() for n in ('linux.uart', 'linux.events')]
    for stream, name in ((u, 'uart'), (e, 'events')):
        check(sha256(stream[:prefix[name+'_prefix_bytes']]).hexdigest() == prefix[name+'_prefix_sha256'], 'different shell prefix')
    nonce = (run/'nonce').read_text('ascii').strip()
    text = e.decode('ascii')
    result = inspect(u, text, nonce)
    check(result == load(run/'review.json'), 'saved completion differs')
    check(u.count(b'0x19d9') == 1 and text.splitlines()[-1].startswith('SHELL_WIRE_DONE '), 'negative control anchors')
    for uart, events in ((u.replace(b'0x19d9', b'0x19d8'), text), (u, ''.join(text.splitlines(True)[:-1]))):
        try:
            inspect(uart, events, nonce)
        except ValueError:
            continue
        raise ValueError('bad evidence accepted')
    return dict(**result, uart_bytes=len(u), events_bytes=len(e), rejected_controls=2,
                model_sha256=pins['model'], stock_kit_sha256=pins['CANDIDATE.sha256'],
                firmware_sha256=pins['fw_payload.bin'], elf_sha256=entry['embedded_benchmark']['elf_sha256'])


if __name__ == '__main__':
    p = ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    try:
        result = review(p.parse_args().run)
    except (OSError, ValueError, KeyError, IndexError):
        # Some parser errors contain command rows. Never print a private challenge.
        raise SystemExit('Stock RTL shell completion review rejected.') from None
    print(json.dumps(result, indent=2))
