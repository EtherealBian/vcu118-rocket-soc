#!/usr/bin/env python3
"""Create a semantic negative control: change an LZ4 literal, leave the guest CRC unchanged.
Prove with the host liblz4 that the new block still decodes to precisely the declared length.
Both outer ROM5 frames are valid. Used only in the simulator.
"""
import argparse,ctypes as C,hashlib,json,zlib
from ctypes.util import find_library
from pathlib import Path
from uart_frame import encode

def create(stage,raw,out):
    meta=json.loads((stage/'stage.json').read_text());b=(stage/'stage.bin').read_bytes();block=(stage/'block.lz4').read_bytes(); original=raw.read_bytes()
    assert b.count(block)==1 and hashlib.sha256(original).hexdigest()==meta['raw_sha256'] and hashlib.sha256(b).hexdigest()==meta['stage_sha256']
    # The LZ4 block ends in literal bytes. Change its last byte, not a length or offset.
    changed=block[:-1]+bytes([block[-1]^0x40]);lib=C.CDLL(find_library('lz4') or 'liblz4.so.1');dst=C.create_string_buffer(len(original));lib.LZ4_decompress_safe.argtypes=[C.c_void_p,C.c_void_p,C.c_int,C.c_int];lib.LZ4_decompress_safe.restype=C.c_int
    assert lib.LZ4_decompress_safe(changed,dst,len(changed),len(dst))==len(original) and dst.raw[:-1]==original[:-1] and dst.raw[-1]!=original[-1] and zlib.crc32(dst.raw)!=zlib.crc32(original)
    with out.open('xb') as f:f.write(encode(b.replace(block,changed)))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('raw',type=Path);p.add_argument('out',type=Path);a=p.parse_args();create(a.stage,a.raw,a.out)
