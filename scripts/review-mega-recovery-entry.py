#!/usr/bin/env python3
"""Read only the completed reset-to-supervisor window of the running recovery RTL."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
L = runpy.run_path(str(HERE / 'test-mega-recovery-linux.py'))
parse_entry = runpy.run_path(str(HERE / 'review-mega-linux-entry.py'))['inspect']
need = L['need']


def first_window(folder):
    # The writer flushes stdout on every UART byte, then prints a byte count on
    # stderr. Read stderr *first*; never require a later UART character to exist.
    with (folder/'linux.events').open('rb') as fp:
        wire = bytearray()
        while len(wire) < 8192:
            row = fp.readline(512)
            need(row.endswith(b'\n'), 'kernel entry prefix not complete')
            if row.startswith(b'ENTRY_PREFIX '):
                m = re.fullmatch(rb'ENTRY_PREFIX bytes=([1-9][0-9]{0,4})\n', row)
                need(m and int(m[1]) <= 65536, 'invalid UART cut')
                with (folder/'linux.uart').open('rb') as uart:
                    raw = uart.read(int(m[1]))
                need(len(raw) == int(m[1]), 'incomplete UART prefix')
                return raw, bytes(wire), row
            wire.extend(row)
    raise ValueError('no kernel-entry boundary within observer window')


def inspect(raw, wire, crc, bad_uart, preload, ref):
    witness = parse_entry(crc.decode('ascii'), bad_uart, wire.decode('ascii'), raw, preload)
    need(witness == ref['witness'], 'different recovery architectural witness')
    evidence = {k:sha256(data).hexdigest() for k,data in (
        ('boot.uart',raw), ('boot.events',wire), ('crc.uart',bad_uart), ('crc.events',crc))}
    need(evidence == ref['evidence'], 'entry differs byte-for-byte from the original run')
    return dict(witness=witness, evidence_sha256=evidence, uart_prefix_bytes=len(raw), events_prefix_bytes=len(wire))


def live(pid, folder, fw):
    proc = Path('/proc')/str(pid)
    need((proc/'exe').samefile(folder/'model') and (proc/'cwd').samefile(folder) and
         (proc/'fd/1').samefile(folder/'linux.uart') and (proc/'fd/2').samefile(folder/'linux.events'),
         'not this live recovery model or output streams')
    args = (proc/'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    need(len(args)==6 and Path(args[0]).samefile(folder/'model') and args[1]=='valid' and
         all(Path(a).samefile(b) for a,b in zip(args[2:5], (fw,folder/'prefix.frame',folder/'commands.txt'))) and
         args[5]==(folder/'nonce').read_text().strip(), 'not the bound live stimulus')


def review(physical, kit, previous, release, vt, out, pid):
    fw = release/'fw_payload.bin'
    if pid is not None: live(pid,out,fw)
    L['qualified'](physical,kit,previous,vt)
    bound = L['binding'](release,previous,kit,vt,out); bound['model'] = L['h'](out/'model')
    need(bound == json.loads((out/'bound.json').read_bytes()),'bound recovery inputs changed')
    ref = L['doc'](L['ENTRY']); rom_ref = L['doc']('perf-mega175-recovery-rom.json')
    need(L['rom_prefix'](out) == rom_ref, 'previous ROM control no longer matches')
    raw,wire,marker = first_window(out)
    crc,bad = [(out/n).read_bytes() for n in ('crc.events','crc.uart')]
    data = inspect(raw,wire,crc,bad,fw.stat().st_size-8,ref)
    if pid is not None: live(pid,out,fw)
    return dict(scope='Cold-reset recovery ChipTop RTL; preloaded behavioral external TL RAM except the UART entry bytes. Through MRET and a bounded S-mode retirement window only. Not a userspace, STA or board result.',
                physical_kit_sha256=bound['CANDIDATE.sha256'],model_sha256=bound['model'],
                bound_sha256=L['h'](out/'bound.json'),observer_sha256=bound['boot.cpp'],
                firmware_sha256=bound['fw_payload.bin'],kernel_sha256=bound['Image'],
                bounded_events_including_marker_sha256=sha256(wire+marker).hexdigest(),**data)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('physical','kit','previous','release','vt','out'):
        p.add_argument(key,type=lambda s:Path(s).resolve(strict=True))
    p.add_argument('--pid',type=int,help='additionally check live Linux process, arguments and open capture files')
    a=p.parse_args(); print(json.dumps(review(**vars(a)),indent=2))
