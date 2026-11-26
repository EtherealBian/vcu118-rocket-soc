#!/usr/bin/env python3
"""Create deliberately malformed wire inputs; no serial port or FPGA programming."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from uart_frame import HEADER, MAGIC, MAX_BYTES, encode

def cases(data):
    good=encode(data)
    # A short CRC case specifically proves that a complete but corrupt frame parks.
    one=encode(b'X')
    return {'uart5-bare':good,'uart5-badcrc':one[:-1]+b'Y',
            'uart5-badmagic':b'BADMAGIC'+good[8:16],
            'uart5-badlength':HEADER.pack(MAGIC,MAX_BYTES+1,0),
            'uart5-truncated':good[:17]}

if __name__=='__main__':
    out=Path(sys.argv[2]); out.mkdir()
    for name,frame in cases(Path(sys.argv[1]).read_bytes()).items():
        (out/(name+'.frame')).write_bytes(frame)
