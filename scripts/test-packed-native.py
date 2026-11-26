#!/usr/bin/env python3
"""Native decoder tests for bounds, valid overlap, CRC, and three production vectors."""
import argparse,ctypes as C,json,subprocess,tempfile,zlib
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',action='append',nargs=2,type=Path,default=[],metavar=('BLOCK','ORIGINAL'));a=p.parse_args()
    pos=neg=0
    with tempfile.TemporaryDirectory() as d:
        dll=Path(d)/'decode.so';subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',root/'software/boot-pack/decode.c','-o',dll],check=True)
        lib=C.CDLL(str(dll));unpack=lib.unpack_block;unpack.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t];unpack.restype=C.c_int
        crc=lib.unpack_crc32;crc.argtypes=[C.c_void_p,C.c_size_t];crc.restype=C.c_uint32
        def test(block,n,want=None):
            nonlocal pos,neg
            dst=C.create_string_buffer(b'Z'*(n+32),n+32);result=unpack(block,len(block),C.byref(dst,16),n);b=dst.raw
            assert b[:16]==b'Z'*16 and b[-16:]==b'Z'*16
            if want is None:assert result==0;neg+=1
            else:assert result==1 and b[16:-16]==want and crc(C.byref(dst,16),n)==zlib.crc32(want);pos+=1
        test(b'\x10x',1,b'x');test(b'\x14A\x01\0\x50abcde',14,b'A'*9+b'abcde');test(b'\xf0\xff\x00'+bytes(270),270,bytes(270))
        for block,n in [(b'',4),(b'\x10',1),(b'\x20x',2),(b'\xf0\xff',270),(b'\xf0\xff\x00'+bytes(270),269),(b'\x10a\0\0\x50abcde',10),(b'\x10a\x02\0\x50abcde',10),(b'\x10a\x01',8),(b'\x1fa\x01\0\xff',32),(b'\x14a\x01\0\x50abcde',13),(b'\x10x',0),(b'\x10x',2)]:test(block,n)
        for block,raw in a.fixture:test(block.read_bytes(),raw.stat().st_size,raw.read_bytes())
    print(json.dumps(dict(native_good=pos,native_rejected=neg,canaries='unchanged',crc='matched zlib on all positives'),indent=2))

if __name__=='__main__':main()
