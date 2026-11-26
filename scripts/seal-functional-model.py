#!/usr/bin/env python3
"""Seal the generated HDL used for a functional ChipTop (never a board-programming kit)."""
import argparse
from hashlib import sha256
from pathlib import Path


def seal(cy, gen, rom, kit, overlay):
    cy, gen, rom = (p.resolve(strict=True) for p in (cy, gen, rom))
    name = gen.name
    if (cy not in gen.parents or not name.endswith('.'+overlay.stem+'VCU118Config')):
        raise ValueError('generated class and configuration overlay differ')
    paths = [Path(s).resolve(strict=True) for s in (gen/(name+'.vsrcs.f')).read_text().splitlines() if s.strip()]
    names = {p.name for p in paths}
    if (len(paths) <= 300 or len(paths) != len(names) or not {'ChipTop.sv','TLROM.sv'} <= names
            or not all(cy in p.parents and p.suffix in ('.v','.sv') for p in paths)):
        raise ValueError('unexpected or ambiguous HDL sources')
    kit.mkdir(); (kit/'rtl').mkdir(); (kit/'rom').mkdir(); sums = {}
    def put(key, data):
        (kit/key).write_bytes(data); sums[key] = sha256(data).hexdigest()
    for path in paths:
        put('rtl/'+path.name, path.read_bytes())
    put('sources.f', ''.join('rtl/'+p.name+'\n' for p in paths).encode())
    for suffix in ('bin','elf'):
        put('rom/sdboot.'+suffix, rom.with_suffix('.'+suffix).read_bytes())
    put('board.dts', (gen/(name+'.dts')).read_bytes()); put('config.scala', overlay.read_bytes())
    (kit/'CANDIDATE.sha256').write_text(''.join(f'{sums[k]}  {k}\n' for k in sorted(sums)))


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('cy','gen','rom','kit','overlay'): ap.add_argument(arg,type=Path)
    a=ap.parse_args(); seal(a.cy,a.gen,a.rom,a.kit,a.overlay)
