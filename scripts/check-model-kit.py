#!/usr/bin/env python3
"""Reject a simulator object directory built with a different kit's manifest."""
import argparse
import hashlib
from pathlib import Path
import shlex


def check(obj, kit):
    manifest = (kit / 'sources.f').resolve(strict=True)
    rows = (obj / 'VChipTop__verFiles.dat').read_text().splitlines()
    commands = [row[3:-1] for row in rows if row.startswith('C "') and row.endswith('"')]
    if len(commands) != 1:
        raise ValueError('expected one recorded Verilator invocation')
    argv = shlex.split(commands[0])
    if argv.count('-F') != 1 or argv[-1] == '-F' or Path(argv[argv.index('-F')+1]).resolve() != manifest:
        raise ValueError('simulator built from another kit/manifest')
    # Verilator 5.022's S rows record size, inode, ctime sec/ns and mtime
    # sec/ns. Compare those as well as current content: replacing a kit in
    # place and regenerating its manifest must not validate an old model.
    stamps = {}
    for row in rows:
        if row.startswith('S '):
            fields = shlex.split(row)
            if len(fields) != 8: raise ValueError('unexpected Verilator source timestamp format')
            path = Path(fields[-1])
            if path in stamps: raise ValueError('duplicate recorded source: '+str(path))
            stamps[path] = tuple(map(int, fields[1:7]))
    # Verify the kit being identified still contains precisely the HDL inputs it declares.
    sums = {}
    for line in (kit / 'CANDIDATE.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if name in sums: raise ValueError('duplicate input: '+name)
        sums[name] = digest
    sources = manifest.read_text().splitlines()
    if len(set(sources)) != len(sources) or len(sources) < 300: raise ValueError('unexpected source list')
    for name in ['sources.f', *sources]:
        path = (kit / name).resolve(strict=True)
        st = path.stat()
        expected = (st.st_size, st.st_ino, *divmod(st.st_ctime_ns, 10**9), *divmod(st.st_mtime_ns, 10**9))
        if stamps.get(path) != expected: raise ValueError('source absent or changed since Verilation: '+name)
        if kit.resolve() not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != sums.get(name):
            raise ValueError('kit HDL integrity check failed: '+name)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('obj', type=Path); p.add_argument('kit', type=Path)
    a = p.parse_args(); check(a.obj, a.kit); print('SIMULATOR_KIT_MANIFEST_AND_CURRENT_RTL_VERIFIED')
