#!/usr/bin/env python3
"""Correlate the RTL timebase witness, ROM declarations and locked Linux ELF.

The ELF is inspected, not executed. No score, physical clock or Linux syscall
latency is inferred from this M-mode experiment.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]


def require(value, message):
    if not value:
        raise ValueError(message)


def inspect_clock_calls(elf):
    # Resolve guest VAs through executable PT_LOAD entries, not file offsets
    # copied from an objdump. Decode both JALs (not just a symbol name).
    require(elf[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', elf, 18)[0] == 243,
            'expected RV64 little-endian ELF')
    off, = struct.unpack_from('<Q', elf, 32)
    entsize, count = struct.unpack_from('<HH', elf, 54)
    require(entsize == 56 and off + entsize * count <= len(elf), 'invalid program headers')
    segments = [struct.unpack_from('<IIQQQQQQ', elf, off+i*entsize) for i in range(count)]

    def read(addr, size):
        places = [p+addr-v for kind, flags, p, v, _, n, _, _ in segments
                  if kind == 1 and flags & 1 and v <= addr and addr+size <= v+n]
        require(len(places) == 1 and places[0]+size <= len(elf), 'ambiguous executable address')
        return elf[places[0]:places[0]+size]

    for pc in (0x106ac, 0x10f3a):
        require(read(pc-2, 2) == b'\x01\x45', 'clock id is not zero')  # c.li a0,0
        word, = struct.unpack('<I', read(pc, 4))
        rel = ((word >> 31) << 20 | ((word >> 12) & 255) << 12 |
               ((word >> 20) & 1) << 11 | ((word >> 21) & 1023) << 1)
        if rel & (1 << 20):
            rel -= 1 << 21
        require(word & 0xfff == 0xef and pc+rel == 0x147ac, 'not JAL ra to clock wrapper')
    require(struct.unpack('<III', read(0x147ac, 12)) == (0x50693, 0x07100893, 0x73),
            'expected mv a3,a0; li a7,113; ecall')
    return {'start_call_pc': '0x106ac', 'stop_call_pc': '0x10f3a', 'ecall_pc': '0x147b4',
            'clock_id': 0, 'syscall': 113}


def examine(text, pbus, timebase):
    m = re.fullmatch(r'RTC intervals=(\d+) first=(\d+) last=(\d+) period=(\d+)\n'
                     r'GUEST ticks=(\d+) lower=(\d+) upper=(\d+)\n'
                     r'IRQ compare=(\d+) threshold=(\d+) trap=(\d+) disarm=(\d+) mret=(\d+)\n', text)
    require(m, 'incomplete tick/guest/IRQ witness')
    n, first, last, period, ticks, lo, hi, cmp, edge, trap, disarm, ret = map(int, m.groups())
    require(timebase > 0 and period > 0 and pbus == period * timebase, 'ROM and measured divider differ')
    require(n > ticks == 256 and 0 < first < last and last-first == n*period,
            'inconsistent per-edge witness')
    require((period-1)*ticks < lo <= period*ticks <= hi < (period+1)*ticks,
            'MMIO/CSR brackets inconsistent or too wide to discriminate a one-cycle error')
    require(cmp > ticks and edge == first+(cmp-1)*period and edge <= trap < disarm <= ret < last
            and disarm < edge+period, 'timer trap is not tied to armed compare tick')
    return {'edge_intervals': n, 'first_tick_edge': first, 'last_tick_edge': last,
            'uncore_edges_per_tick': period, 'guest_mtime_ticks': ticks, 'guest_mcycle_bounds': [lo, hi],
            'irq_compare_value': cmp, 'threshold_edge': edge, 'mcause_update_edge': trap,
            'compare_disarmed_edge': disarm, 'mret_edge': ret}


def inspect_uart(raw, result):
    prefix = b'UART5_READY v1\r\nUART5_HANDOFF\r\nT'
    expected = prefix + struct.pack('<II', *result['guest_mcycle_bounds']) + b'K'
    require(raw == expected, 'decoded UART disagrees with interval witness')


def review(out, exe):
    def doc(stem):
        return json.loads((ROOT/'docs'/('perf-mega175-'+stem+'.json')).read_bytes())
    pin, ident, link = doc('linux-entry'), doc('linux-identity'), doc('fixed-rom-link')
    elf = exe.read_bytes(); digest = sha256(elf).hexdigest()
    require(digest == pin['inputs']['coremark-g15-gc-lto-ooo-strict.elf'], 'not the strict ELF')
    require(link['rom_dtb_sha256'] == ident['rom_and_dtb_sha256'], 'model and implementation ROM differ')
    witness = (out/'witness.txt').read_text()
    # Bind the binary, frame and host executable to this invocation's input
    # manifest and to the already authenticated stock model. Never publish paths.
    names = ['entry.bin','prefix.frame','model']
    hashes = {}
    for row in (out/'inputs.sha256').read_text().splitlines():
        h, path = row.split('  ', 1); path = (ROOT/Path(path)).resolve(strict=True)
        require(path.name not in hashes and sha256(path.read_bytes()).hexdigest() == h,
                'duplicate or changed run input: '+path.name)
        hashes[path.name] = (h, path)
    wanted = {'CANDIDATE.sha256','VChipTop__ALL.a','VChipTop___024root.h','verilated.o',
              'verilated_threads.o','test-mega-timebase.sh','review-mega-timebase.py','uart_frame.py',
              'mega_timebase.cpp','mega_timebase.S','layout.ld','rocket_chiptop.cpp',*names,
              *(k for k in link['inputs'] if k.startswith('chiptop_') and k.endswith('.hpp'))}
    require(set(hashes) == wanted, 'unexpected run input set')
    for k in ('CANDIDATE.sha256','VChipTop__ALL.a','VChipTop___024root.h'):
        require(hashes[k][0] == pin['models']['stock'][k], 'wrong stock model: '+k)
    for k in wanted & link['inputs'].keys():
        if k != 'model': require(hashes[k][0] == link['inputs'][k], 'changed shared inputs: '+k)
    for name in names: require(hashes[name][1] == (out/name).resolve(), 'mixed diagnostic artifacts')
    prefix = (out/'entry.bin').read_bytes()[:8]
    require((out/'prefix.frame').read_bytes() == struct.pack('<8sII', b'VCU118U5',8,zlib.crc32(prefix))+prefix,
            'prefix not bound to entry')
    observed = examine(witness, ident['declared_pbus_hz'], ident['declared_timebase_hz'])
    raw = (out/'rx.uart').read_bytes(); inspect_uart(raw, observed)
    return {'scope': 'Stock functional model, M-mode diagnostic. Linux ELF clock calls inspected only; neither Linux timekeeping nor board clock or score measured.',
            'model_kit_seal': pin['models']['stock']['CANDIDATE.sha256'],
            'model_archive_sha256': pin['models']['stock']['VChipTop__ALL.a'],
            'rom_and_dtb_sha256': link['rom_dtb_sha256'], 'linux_elf_sha256': digest,
            'diagnostic_sha256': {n: hashes[n][0] for n in names},
            'uart_sha256': sha256(raw).hexdigest(),
            'locked_elf_timer': inspect_clock_calls(elf),
            'model_witness': observed}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('out', type=Path); p.add_argument('strict_elf', type=Path)
    a = p.parse_args(); print(json.dumps(review(a.out, a.strict_elf), indent=2))
