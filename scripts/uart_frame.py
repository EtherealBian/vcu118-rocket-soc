#!/usr/bin/env python3
"""Build a ROM5 USB-UART frame; no device discovery, serial I/O or disk imaging."""
import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

HEADER = struct.Struct('<8sII')
MAGIC = b'VCU118U5'
MAX_BYTES = 30 * 1024 * 1024


def encode(payload):
    if not 1 <= len(payload) <= MAX_BYTES:
        raise ValueError('payload must contain 1 byte through 30 MiB (inclusive)')
    return HEADER.pack(MAGIC, len(payload), zlib.crc32(payload)) + payload


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('payload', type=Path)
    ap.add_argument('frame', type=Path, help='new ordinary file')
    a = ap.parse_args()
    with a.payload.open('rb') as src:
        data = src.read(MAX_BYTES + 1)
    frame = encode(data)
    with a.frame.open('xb') as dest:
        dest.write(frame)
    print(json.dumps(dict(format='VCU118U5', payload_bytes=len(data),
                          payload_sha256=hashlib.sha256(data).hexdigest(),
                          frame_sha256=hashlib.sha256(frame).hexdigest())))

if __name__ == '__main__':
    main()
