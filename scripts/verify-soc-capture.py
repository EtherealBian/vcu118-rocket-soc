#!/usr/bin/env python3
"""Offline check of a physical UART5 capture. Emit digests, never target IDs or raw logs."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from uart_frame import encode


def sha(data):
    return hashlib.sha256(data).hexdigest()


def metadata(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def check_program(lines):
    # Tcl prints the script before executing it. Only actual result lines count.
    events = [s for s in lines if s.startswith(('VOLATILE_PROGRAM_', 'PROGRAM_READBACK '))]
    body = [f'PROGRAM_READBACK REGISTER.CONFIG_STATUS.SLR{i}.{k}={v}' for i in range(3)
            for k, v in [('BIT[14]_DONE_PIN', 1), ('BIT[00]_CRC_ERROR', 0)]]
    if len(events) != 8 or not events[0].startswith('VOLATILE_PROGRAM_START ') or events[1:] != body + ['VOLATILE_PROGRAM_AND_READBACK_PASS']:
        raise ValueError('missing, failed, duplicated or out-of-order programming readback')


def check_uart(raw, mode, nonce):
    text = raw.decode('ascii').replace('\r\n', '\n')
    ready, jump = 'UART5_READY v1\n', 'UART5_HANDOFF\n'
    if not text.startswith(ready) or text.count(ready) != 1 or text.count(jump) != 1 or not text[len(ready):].startswith(jump):
        raise ValueError('unrecognized or repeated UART boot epoch')
    guest = text[len(ready) + len(jump):]
    if re.search(r'UART5_STOP|Kernel panic|(?:VCU118_(?:ADDR|DIAG)_FAIL)|SOC_SELFTEST_FAILED', text):
        raise ValueError('failure in console')
    markers = {
        'bare': ('VCU118_DIAG_START v1', 'VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced'),
        'address': ('VCU118_ADDR_START v1', 'VCU118_ADDR_PASS windows=4 bytes_each=4096 passes=2 flush_lines=512'),
    }
    if mode in markers:
        if nonce is not None or guest.splitlines() != list(markers[mode]):
            raise ValueError('invalid bare-metal transcript')
    elif mode == 'linux':
        if not isinstance(nonce, str) or not re.fullmatch('[a-f0-9]{14}', nonce):
            raise ValueError('no unique live challenge')
        pattern = (r'^VCU118_INITRAMFS_READY\n.*?^SOC_CHECK_PASS bytes=16777216 passes=[1-9]\d* elapsed_s=\d+\n'
                   r'.*?^# .*?^(?:# )?BOARD_42_' + nonce + r'\n')
        if not re.search(pattern, guest, re.M | re.S):
            raise ValueError('missing userspace test or independent shell response')
    else:
        raise ValueError('unknown diagnostic')


def public_record(run, capture, payload):
    info = metadata(capture/'pass.json'); impl = metadata(capture/'implementation.json'); bit = sha((run/'obj/VCU118FPGATestHarness.bit').read_bytes())
    if bit != impl['bit_sha256'] or bit != info['bit_sha256'] or not all(impl[k] is True for k in ('board_io_inventory_known', 'board_internal_coverage_met', 'route_and_constrained_timing_met')):
        raise ValueError('unreviewed or mismatched implementation')
    for name, digest in impl['reports_sha256'].items():
        if not re.fullmatch(r'[a-z-]+\.rpt', name) or sha((run/'obj/report'/name).read_bytes()) != digest:
            raise ValueError('route report mismatch')
    pins = metadata(capture/'board-io.json')
    if (pins['total'], pins['ddr_c1']) != (133, 115) or sha((run/'obj/routed-io.rpt').read_bytes()) != pins['io_sha256']:
        raise ValueError('pin review mismatch')
    frame = (capture/'payload.frame').read_bytes(); data = payload.read_bytes(); meta = metadata(capture/'frame.json')
    expected = dict(format='VCU118U5', payload_bytes=len(data), payload_sha256=sha(data), frame_sha256=sha(frame))
    if frame != encode(data) or meta != expected or meta != info['uart5_frame'] or info['uart5_handoff'] is not True:
        raise ValueError('framed file or handoff mismatch')
    check_program((capture/'vivado-console.txt').read_text(encoding='utf-8-sig').splitlines())
    raw = (capture/'uart.txt').read_bytes(); mode = info['test']; digest = sha(raw)
    if digest != info['uart_sha256'].lower() or info['challenge_sent'] is not (mode == 'linux'):
        raise ValueError('bad transcript identity or challenge state')
    check_uart(raw, mode, info['challenge_nonce'])
    return dict(mode=mode, utc=info['utc'], bit_sha256=bit, uart='115200 8N1', **expected,
                uart_sha256=digest, slr_done=[1,1,1], slr_crc_error=[0,0,0], volatile_configuration=True,
                shell_challenge_verified=(mode == 'linux'))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('run','capture','payload'): p.add_argument(n, type=Path)
    a=p.parse_args(); print(json.dumps(public_record(a.run,a.capture,a.payload),indent=2))
