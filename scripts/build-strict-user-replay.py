#!/usr/bin/env python3
"""Build private 256 KiB diagnostic RAMs from two captured strict guest windows."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
from uart_frame import encode

ROOT = Path(__file__).resolve().parents[1]
BASE, TABLES, USER = 0x80000000, 0x80010000, 0x80020000
RX, RW = 0xdb, 0xd7  # RISC-V leaf PTE flags, including U/A/D; no writable text.
AREAS = [('text', 44712), ('rw', 3120), ('stack', 1728), ('heap', 2000)]

def require(ok, message):
    if not ok:
        raise ValueError(message)


def build(guest, elf, prefix, tail=False):
    folder = guest/'replay'; folder.mkdir()
    snap, end = [json.loads((guest/(tag+'.json')).read_text()) for tag in ('in', 'out')]
    entry = 0x10af0 if tail else 0x106b0
    for state, pc in ((snap, entry), (end, 0x10f3a)):
        require(state['priv'] == 0 and state['satp'] >> 60 == 8 and state['pc'] == pc,
                'expected an Sv39 user window fence')
        require(len(state['regs']) == 32 and state['regs'][0] == 0, 'expected all GPRs')
    if tail:
        require(snap['regs'][14] == 23992 and end['regs'][14] == 24000 and
                snap['regs'][25] == end['regs'][25] == 24000, 'wrong target-tail round boundaries')
        require(snap['satp'] == end['satp'], 'changed user address space')
    areas = snap['areas']
    require(areas == end['areas'] and [(k,n) for k,_,n in areas] == AREAS, 'bad memory spans')
    require([x[1] for x in areas] == [0x10158, 0x20f50, snap['regs'][2]-1536, snap['regs'][9]],
            'wrong RX, RW, stack or heap origin')
    ram = bytearray(256*1024); pages = {}; tables = {(): TABLES}

    def pa(va):
        return pages[va>>12][0] + (va & 4095)

    def load(va, data, flags):
        for i, byte in enumerate(data):
            addr = va+i; vpn = addr>>12
            if vpn not in pages:
                pages[vpn] = USER + 4096*len(pages), flags
            require(pages[vpn][1] == flags and 0 <= pa(addr)-BASE < len(ram), 'bad RAM mapping')
            ram[pa(addr)-BASE] = byte

    def pte(table, slot, target, flags):
        struct.pack_into('<Q', ram, table-BASE+8*slot, ((target>>12)<<10) | flags)

    load(0x10000, elf[:0xfb48], RX)
    load(0x20f50, elf[0xff50:0xff50+0x1c8]+bytes(0xc30-0x1c8), RW)
    compare, oracles = [], []
    for name, va, size in areas:
        before, after = [(guest/(tag+'-'+name)).read_bytes() for tag in ('in', 'out')]
        require(len(before) == len(after) == size, 'incomplete memory dump')
        if name == 'text':
            require(before == after == elf[va-0x10000:va-0x10000+size], 'changed text')
            continue
        load(va, before, RW)
        require(pa(va+size-1) == pa(va)+size-1, 'span crosses discontiguous pages')
        compare.extend([f'li t0,{pa(va)}', f'la t1,exp_{name}', f'li t2,{size}', 'jal ra,compare'])
        oracles.append(f'exp_{name}: .incbin "out-{name}"')
    for vpn, (phys, flags) in pages.items():
        prefix_key = ()
        for index in (vpn>>18, (vpn>>9) & 511):
            key = prefix_key+(index,)
            if key not in tables:
                addr = TABLES+len(tables)*4096
                require(addr < USER and index < 512, 'Sv39 page table overflow')
                tables[key] = addr; pte(tables[prefix_key], index, addr, 1)
            prefix_key = key
        pte(tables[prefix_key], vpn & 511, phys, flags)
    expected = end['regs'][:]
    # Execute the unchanged clock-call JAL and two libc instructions before ECALL.
    expected[1], expected[13], expected[17] = 0x10f3e, expected[10], 113
    slots = dict(ENTRY=hex(entry), SATP=str((8<<60) | (TABLES>>12)), COMPARE_MEMORY='\n'.join(compare),
                 RESTORE='\n'.join(f'ld x{i},{8*i}(x31)' for i in range(1,32)),
                 SAVE='\n'.join(f'sd x{i},{8*i}(x31)' for i in range(1,31)),
                 INITIAL=','.join(map(hex, snap['regs'])), EXPECTED=','.join(map(hex, expected)),
                 ORACLES='\n'.join(oracles))
    source = (ROOT/'tests/mega_user_replay_entry.S.in').read_text()
    for key, value in slots.items():
        require(source.count('@'+key+'@') == 1, 'missing or duplicate assembly placeholder')
        source = source.replace('@'+key+'@', value)
    asm, image, binary = (folder/('entry.'+ext) for ext in ('S', 'elf', 'bin'))
    asm.write_text(source)
    subprocess.run([prefix+'gcc', '-march=rv64imac_zicsr', '-mabi=lp64', '-mno-relax',
                    '-mcmodel=medany', '-fno-pie', '-no-pie', '-nostdlib', '-static',
                    '-Wl,--build-id=none,--no-relax', '-T', ROOT/'software/bare/layout.ld',
                    asm, '-o', image], cwd=guest, check=True)
    subprocess.run([prefix+'objcopy', '-O', 'binary', image, binary], check=True)
    boot = binary.read_bytes(); require(8 < len(boot) < TABLES-BASE, 'stub exceeds reserved RAM')
    ram[:len(boot)] = boot
    (folder/'mem.bin').write_bytes(ram); (folder/'prefix.frame').write_bytes(encode(boot[:8]))
    print(guest.name, 'pages', len(pages), 'tables', len(tables), 'stub bytes', len(boot))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('guest', type=Path); parser.add_argument('elf', type=Path)
    parser.add_argument('tool_prefix', help='RISC-V GCC/objcopy executable prefix')
    parser.add_argument('--target-tail', action='store_true', help='require an eight-round tail of the 24000-round workload')
    args = parser.parse_args(); elf = args.elf.read_bytes()
    ref = json.loads((ROOT/'docs/perf-strict-user-window.json').read_bytes())
    require(sha256(elf).hexdigest() == ref['elf_sha256'], 'unexpected release ELF')
    for seed in ('performance', 'validation'):
        build(args.guest.resolve()/seed, elf, args.tool_prefix, args.target_tail)
