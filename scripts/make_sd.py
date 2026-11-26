#!/usr/bin/env python3
"""Create a NEW regular-file SD image only. Stock VCU118 ROM reads LBA34 + 30 MiB."""
import argparse, hashlib, os, struct, uuid, zlib
from pathlib import Path
SECTOR, START, LOAD = 512, 34, 30 << 20
SECTORS = (64 << 20) // SECTOR
ENTRY_SIZE, COUNT = 128, 128
APFS = uuid.UUID('7c3457ef-0000-11aa-aa11-00306543ecac') # bootrom ignores partition type

def make(payload, dest, compact=False):
    src,dst=Path(payload),Path(dest)
    if not src.is_file() or not 0 < src.stat().st_size <= LOAD:
        raise ValueError('payload must be a nonempty regular file, at most 30 MiB')
    if dst.is_symlink() or dst.exists() or str(dst.resolve()).startswith("/dev/") or str(dst).startswith(chr(92)*2) or dst.suffix.lower()!=".img":
        raise ValueError('output must be a new regular .img, not a device or existing file')
    data=src.read_bytes()
    if not 0<len(data)<=LOAD: raise ValueError('payload size changed')
    disk=uuid.uuid5(uuid.NAMESPACE_OID,hashlib.sha256(data).hexdigest()); part=uuid.uuid5(disk,'vcu118-boot')
    table=bytearray(COUNT*ENTRY_SIZE); last=SECTORS-1
    sectors=(len(data)+SECTOR-1)//SECTOR if compact else LOAD//SECTOR
    struct.pack_into('<16s16sQQQ72s',table,0,APFS.bytes_le,part.bytes_le,START,START+sectors-1,0,'VCU118 payload'.encode('utf-16le'))
    def header(at,backup,entries):
        h=bytearray(SECTOR); struct.pack_into('<8sIIIIQQQQ16sQIII',h,0,b'EFI PART',0x10000,92,0,0,at,backup,START,last-33,disk.bytes_le,entries,COUNT,ENTRY_SIZE,zlib.crc32(table)); struct.pack_into('<I',h,16,zlib.crc32(h[:92])); return h
    mbr=bytearray(SECTOR); struct.pack_into('<B3sB3sII',mbr,446,0,b'\0\2\0',0xee,b'\xff'*3,1,last); mbr[510:]=b'\x55\xaa'
    with dst.open('xb') as f:
        f.truncate(SECTORS*SECTOR); f.write(mbr); f.write(header(1,last,2)); f.write(table); f.seek(START*SECTOR); f.write(data)
        f.seek((last-32)*SECTOR); f.write(table); f.write(header(last,1,last-32)); f.flush(); os.fsync(f.fileno())
    return hashlib.sha256(data).hexdigest()
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--compact',action='store_true',help='size GPT partition 1 to payload for ROM4; unused space remains zero'); p.add_argument('payload'); p.add_argument('image'); a=p.parse_args(); print('payload_sha256='+make(a.payload,a.image,compact=a.compact))
