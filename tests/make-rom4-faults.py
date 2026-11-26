#!/usr/bin/env python3
"""Files for negative ROM4 regression, NEVER write to source media or a device."""
from pathlib import Path
import argparse,struct,zlib
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('directory',type=Path);a=p.parse_args();raw=a.source.read_bytes(); assert len(raw)==64<<20 and raw[512:520]==b'EFI PART';a.directory.mkdir(exist_ok=False)
for mode in ('gpt-badheader','gpt-badtable','gpt-bounds'):
    b=bytearray(raw);h=512;t=1024
    if mode=='gpt-badheader':b[h+16]^=1
    if mode=='gpt-badtable':b[t+16383]^=1 # unused entry -> correct wire CRC and wrong whole-table CRC
    if mode=='gpt-bounds':
        struct.pack_into('<Q',b,t+40,34+61440) # 30 MiB + one sector, both primary GPT checksums are now valid
        struct.pack_into('<I',b,h+88,zlib.crc32(b[t:t+16384]));b[h+16:h+20]=bytes(4);struct.pack_into('<I',b,h+16,zlib.crc32(b[h:h+92]))
    out=a.directory/(mode+'.img');out.write_bytes(b);print(mode,out)
