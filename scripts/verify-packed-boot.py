#!/usr/bin/env python3
"""Recheck the physical ROM5 envelope and the packed-stage marker against the original file."""
import argparse, hashlib, importlib.util, json, zlib
from pathlib import Path

here=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('vcu_capture',here/'verify-soc-capture.py'); capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)
sha=lambda x:hashlib.sha256(x).hexdigest()


def inspect(raw, stage, block, meta, uart):
    digest=sha(raw);crc=f'{zlib.crc32(raw):08x}'; want=dict(raw_bytes=len(raw),raw_sha256=digest,raw_crc32=crc,block_bytes=len(block),block_sha256=sha(block),stage_bytes=len(stage),stage_sha256=sha(stage),wire_bytes_saved=len(raw)-len(stage),stage_copy_address='0x84000000',output_address='0x80000000',stage_stack='0x87fff000')
    if not (0<len(raw)<=30<<20 and 0<len(block)<len(stage)<=30<<20 and len(stage)%8==0 and stage.count(block)==1 and all(meta.get(k)==v for k,v in want.items())):raise ValueError('stage inputs or placement manifest differ')
    rows=uart.decode('ascii').replace('\r\n','\n').splitlines();ok=f'UART5_PACK1_OK bytes={len(raw)} crc32={crc}'
    good=[s for s in rows if s.startswith('UART5_PACK1_')];
    if rows[:3]!=['UART5_READY v1','UART5_HANDOFF',ok] or good!=[ok]:raise ValueError('missing, failed or out-of-order board-side decompressed CRC')
    return want


def compare(raw_report,packed_report):
    if (raw_report['mode']!=packed_report['mode'] or raw_report['bit_sha256']!=packed_report['bit_sha256'] or raw_report['payload_sha256']!=packed_report['packed_stage']['raw_sha256'] or not raw_report['shell_challenge_verified'] or not packed_report['shell_challenge_verified']):raise ValueError('comparison requires identical bit, inner firmware and type of live shell check')
    def observed(r):
        t=r.get('host_elapsed_ms')
        if not isinstance(t,dict) or set(t)!={'rom_handoff','shell_prompt','accept'} or any(type(v)!=int for v in t.values()) or not 0<=t['rom_handoff']<=t['shell_prompt']<=t['accept']:
            raise ValueError('both independently verified runs need complete monotonic host observations')
        return t
    a,b=map(observed,(raw_report,packed_report))
    if min(a['accept'],b['accept'])<=0:raise ValueError('invalid observed time')
    return dict(raw_host_elapsed_ms=a,packed_host_elapsed_ms=b,elapsed_ratio_packed_over_raw=round(b['accept']/a['accept'],5),milliseconds_saved_to_shell_response=a['accept']-b['accept'],scope='first byte queued to verified live shell result; host monotonic observations, excludes JTAG programming')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('run','capture','stage_dir','original'):p.add_argument(n,type=Path)
    p.add_argument('--raw-capture',type=Path,help='optional independently verified uncompressed run for timing');a=p.parse_args();s=a.stage_dir
    report=capture.public_record(a.run,a.capture,s/'stage.bin')
    if not report['shell_challenge_verified']:raise ValueError('expected live Linux shell')
    report['packed_stage']=inspect(a.original.read_bytes(),(s/'stage.bin').read_bytes(),(s/'block.lz4').read_bytes(),json.loads((s/'stage.json').read_text()),(a.capture/'uart.txt').read_bytes())
    if a.raw_capture:report['same_firmware_comparison']=compare(capture.public_record(a.run,a.raw_capture,a.original),report)
    print(json.dumps(report,indent=2))
