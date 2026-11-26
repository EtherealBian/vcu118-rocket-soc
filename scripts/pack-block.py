#!/usr/bin/env python3
"""Encode one LZ4 block with the host liblz4, then decode independently in liblz4.
The guest (fixed DDR placement) compiles decode.c and does not ship liblz4.
"""
import argparse
import ctypes as C
from ctypes.util import find_library
import hashlib,json,zlib
from pathlib import Path


def prepare(raw, out):
    if not 0<len(raw)<=30<<20:raise ValueError('original image outside the fixed ROM5 size envelope')
    lib=C.CDLL(find_library('lz4') or 'liblz4.so.1')
    lib.LZ4_versionString.argtypes=[];lib.LZ4_versionString.restype=C.c_char_p
    lib.LZ4_compressBound.argtypes=[C.c_int];lib.LZ4_compressBound.restype=C.c_int
    lib.LZ4_compress_HC.argtypes=[C.c_void_p,C.c_void_p,C.c_int,C.c_int,C.c_int];lib.LZ4_compress_HC.restype=C.c_int
    lib.LZ4_decompress_safe.argtypes=[C.c_void_p,C.c_void_p,C.c_int,C.c_int];lib.LZ4_decompress_safe.restype=C.c_int
    buf=C.create_string_buffer(lib.LZ4_compressBound(len(raw)))
    n=lib.LZ4_compress_HC(raw,buf,len(raw),len(buf),9)
    if not 0<n<=30<<20:raise ValueError('cannot encode within ROM5 bounds')
    block=buf.raw[:n]; check=C.create_string_buffer(len(raw))
    if lib.LZ4_decompress_safe(block,check,n,len(raw))!=len(raw) or check.raw!=raw:raise ValueError('host LZ4 round-trip failed')
    crc=zlib.crc32(raw);tag=f'bytes={len(raw)} crc32={crc:08x}'
    with (out/'block.lz4').open('xb') as f:f.write(block)
    with (out/'payload.h').open('x') as f:f.write(f'#define RAW_BYTES {len(raw)}u\n#define PACK_BYTES {n}u\n#define RAW_CRC 0x{crc:08x}u\n#define PACK_LABEL "{tag}"\n')
    return dict(raw_bytes=len(raw),raw_sha256=hashlib.sha256(raw).hexdigest(),raw_crc32=f'{crc:08x}',block_bytes=n,block_sha256=hashlib.sha256(block).hexdigest(),lz4=lib.LZ4_versionString().decode(),compression_level=9)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('raw',type=Path);p.add_argument('out',type=Path);a=p.parse_args();print(json.dumps(prepare(a.raw.read_bytes(),a.out),indent=2))
