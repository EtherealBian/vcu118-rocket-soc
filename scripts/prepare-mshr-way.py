#!/usr/bin/env python3
"""Move only the MSHR way-select mux across its existing register boundary."""
import argparse
from hashlib import sha256
from pathlib import Path

ORIGINAL_SHA = '138334af570cf8b1e15bfa147c17aa5987f2f7b7117c7bc72282aa6ccdee5e7e'
OLD = b'mshrs.io.req(w).bits.way_en      := Mux(s2_tag_match(w), s2_tag_match_way(w), s2_replaced_way_en)'
NEW = b'mshrs.io.req(w).bits.way_en      := RegNext(Mux(s1_tag_match_way(w).orR, s1_tag_match_way(w), s1_replaced_way_en))'


def patch(src):
    if sha256(src).hexdigest() != ORIGINAL_SHA or src.count(OLD) != 1:
        raise ValueError('unexpected upstream D-cache or ambiguous cut')
    return src.replace(OLD, NEW)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('src', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    data = patch(args.src.read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        if args.out.read_bytes() != data:
            raise ValueError('different existing overlay')
    else:
        with args.out.open('xb') as out:
            out.write(data)
    print('MSHR_WAY_SELECT_OVERLAY', sha256(data).hexdigest())
