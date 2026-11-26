#!/usr/bin/env python3
"""Offline check of a physical UART5 capture. Emit digests, never target IDs or raw logs."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from uart_frame import encode
from dotbench_report import review as review_dotbench
from counter_report import review as review_counters
from cpu_window_report import windows as review_cpu_windows
from sweep_report import review as review_sweep


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
    if re.search(r'UART5_STOP|Kernel panic|(?:VCU118_(?:ADDR|DIAG)_FAIL)|SOC_SELFTEST_FAILED|VCU118_COUNTER_FAIL|VCU118_SWEEP_FAIL|DOT4_FAIL|DOTBENCH_FAIL|LINUX_DOT4_FAILED|LINUX_OSCHECK_FAILED', text):
        raise ValueError('failure in console')
    markers = {
        'bare': ('VCU118_DIAG_START v1', 'VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced'),
        'address': ('VCU118_ADDR_START v1', 'VCU118_ADDR_PASS windows=4 bytes_each=4096 passes=2 flush_lines=512'),
    }
    if mode in markers:
        if nonce is not None or guest.splitlines() != list(markers[mode]):
            raise ValueError('invalid bare-metal transcript')
    elif mode == 'dotbench':
        if nonce is not None:raise ValueError('unexpected shell challenge')
        return {'dot_benchmark':review_dotbench(guest.splitlines())}
    elif mode == 'sweep':
        if nonce is not None:raise ValueError('unexpected shell challenge')
        return {'memory_sweep':review_sweep(guest.splitlines())}
    elif mode == 'cpu-window':
        if nonce is not None:raise ValueError('unexpected shell challenge')
        return {'cpu_window_diagnostic':review_cpu_windows(guest.splitlines())}
    elif mode == 'counters':
        if nonce is not None:raise ValueError('unexpected shell challenge')
        return {'counter_windows':review_counters(guest.splitlines())}
    elif mode == 'dot4':
        if nonce is not None or guest.splitlines() != ['DOT4_MMIO_START', 'DOT4_MMIO_PASS vectors=257 protocol_errors_checked=2']:
            raise ValueError('missing or unexpected bare accelerator output')
    elif mode in ('linux','linux-dot4','linux-oscheck'):
        if not isinstance(nonce, str) or not re.fullmatch('[a-f0-9]{14}', nonce):
            raise ValueError('no unique live challenge')
        pattern = (r'^VCU118_INITRAMFS_READY\n.*?^SOC_CHECK_PASS bytes=16777216 passes=[1-9]\d* elapsed_s=\d+\n'
                   r'.*?^# .*?^(?:# )?BOARD_42_' + nonce + r'\n')
        if mode == 'linux-dot4':
            pattern=pattern.replace(r'.*?^# ',r'.*?^LINUX_DOT4_PASS vectors=257 reserved_rejected=1\n.*?^# ')
            if 'LINUX_DOT4_NO_PLATFORM_DEVICE' in guest:raise ValueError('accelerator absent')
        if mode == 'linux-oscheck':
            pattern=pattern.replace(r'.*?^# ',r'.*?^LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d\n.*?^# ')
        if not re.search(pattern, guest, re.M | re.S):
            raise ValueError('missing userspace test or independent shell response')
    else:
        raise ValueError('unknown diagnostic')


def timing(row, size, shell):
    # Optional for older collectors. These timestamps are observed by the host,
    # starting just before queuing the first byte; not a baud measurement.
    if row is None:return {}
    if not isinstance(row,dict) or set(row)!={'rom_handoff','shell_prompt','accept'}:raise ValueError('invalid monotonic measurement')
    r,p,a=(row[k] for k in ('rom_handoff','shell_prompt','accept'))
    if type(r)!=int or type(a)!=int or not 0<=r<=a or (shell and (type(p)!=int or not r<=p<=a)) or (not shell and p is not None):raise ValueError('impossible host timestamps')
    # Allow 1% baud tolerance and millisecond quantization on either observation.
    if r+3<0.99*(size+16)*10000/115200:raise ValueError('handoff before minimum wire interval')
    return {'host_elapsed_ms':row}


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
    if digest != info['uart_sha256'].lower() or info['challenge_sent'] is not (mode in ('linux','linux-dot4','linux-oscheck')):
        raise ValueError('bad transcript identity or challenge state')
    extra = check_uart(raw, mode, info['challenge_nonce']) or {}
    extra.update(timing(info.get('host_elapsed_ms'),len(data),info['challenge_sent']))
    return dict(mode=mode, utc=info['utc'], bit_sha256=bit, uart='115200 8N1', **expected,
                uart_sha256=digest, slr_done=[1,1,1], slr_crc_error=[0,0,0], volatile_configuration=True,
                shell_challenge_verified=(mode in ('linux','linux-dot4','linux-oscheck')), **extra)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('run','capture','payload'): p.add_argument(n, type=Path)
    a=p.parse_args(); print(json.dumps(public_record(a.run,a.capture,a.payload),indent=2))
