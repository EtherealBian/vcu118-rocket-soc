#!/usr/bin/env python3
"""Map complete, resumed DMI samples to text symbols from the exact unrandomized firmware build."""
import argparse
import bisect
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbol(elf, name):
    matches = re.findall(r'^([0-9a-fA-F]+)\s+[tTrR]\s+' + re.escape(name) + '$', run('nm', '-n', elf), re.M)
    if len(matches) != 1:
        raise ValueError(f'expected one {name} in {elf}')
    return int(matches[0], 16)


class TextSymbols:
    def __init__(self, elf):
        # A preceding data/zero-size symbol or a hole is not a function match.
        rows = re.findall(r'^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[tTwW]\s+(\S+)$',
                          run('nm', '-n', '-S', '--defined-only', elf), re.M)
        self.rows = sorted((int(a, 16), int(n, 16), name) for a, n, name in rows if int(n, 16))
        self.starts = [a for a, _, _ in self.rows]

    def lookup(self, pc):
        i = bisect.bisect_right(self.starts, pc) - 1
        if i >= 0:
            start, size, name = self.rows[i]
            if pc < start + size:
                return f'{name}+0x{pc-start:x}'
        return None


def verify_logged_input(log, firmware):
    # test-rtl-boot.sh prints the preload, disk and simulator SHA lines before launch.
    pattern = r'^([a-f0-9]{64})  ([^\r\n]+)\r?$'
    lines = re.findall(pattern, log.split('JTAG IDCODE=', 1)[0], re.M)
    # Reject joined or incomplete run logs; a later hash in the log is not provenance.
    if len(lines) != 3 or lines[0][0] != sha(firmware):
        raise ValueError('log does not identify matching firmware as the first simulation input')


def verify_elf_bytes(objcopy, elf, binary, extra):
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / 'image.bin'
        subprocess.run([objcopy, '-O', 'binary', *extra, elf, output], check=True)
        if output.read_bytes() != binary.read_bytes():
            raise ValueError('ELF does not reproduce ' + str(binary))


def samples(log):
    for line in log.splitlines():
        m = re.search(r'LINUX_JTAG_SAMPLE cycle=(\d+) (.+) resumed$', line)
        if not m:
            continue
        reg = {}
        for token in m[2].split():
            field = re.fullmatch(r'(csr[0-9a-f]+|x[0-9]+)=0x([0-9a-f]{1,16})', token)
            if not field or field[1] in reg:
                raise ValueError('bad or repeated register in DMI profile')
            reg[field[1]] = int(field[2], 16)
        expected = {'csr'+k for k in ('7b1','7b0','180','142','141','143','342','341','343')} | {'x1','x2','x10','x11'}
        if set(reg) != expected:
            raise ValueError('incomplete register profile')
        yield int(m[1]), reg


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('log', type=Path); ap.add_argument('build', type=Path, help='build-image.sh object directory')
    ap.add_argument('firmware', type=Path, help='binary actually preloaded into the simulated RAM')
    default_tools = Path(os.environ.get('VCU_TOOLS', Path.home()/'.local/share/vcu118-tools'))
    ap.add_argument('--objcopy', default=str(default_tools/'bootlin/bin/riscv64-linux-objcopy'))
    args = ap.parse_args(); kernel = args.build / 'kernel'; fw = args.build / 'opensbi/platform/generic/firmware'
    payload = fw / 'fw_payload.elf'; kern = kernel / 'vmlinux'; binfile = fw / 'fw_payload.bin'
    if sha(args.firmware) != sha(binfile) or re.search(r'^CONFIG_(RANDOMIZE_BASE|RELOCATABLE)=y$', (kernel/'.config').read_text(), re.M):
        raise SystemExit('firmware mismatch or randomized/relocatable kernel not supported')
    log = args.log.read_text(errors='replace')
    verify_logged_input(log, args.firmware)
    verify_elf_bytes(args.objcopy, payload, binfile, [])
    verify_elf_bytes(args.objcopy, kern, kernel/'arch/riscv/boot/Image', ['-R', '.note', '-R', '.note.gnu.build-id', '-R', '.comment', '-S'])
    fw_base = symbol(payload, '_fw_start'); phys = symbol(payload, 'payload_bin'); virt = symbol(kern, '_start')
    image = (kernel / 'arch/riscv/boot/Image').read_bytes(); offset = phys - fw_base
    if offset <= 0 or image[56:60] != b'RSC\x05' or binfile.read_bytes()[offset:offset+len(image)] != image:
        raise SystemExit('kernel Image not embedded at expected payload symbol')
    opensbi = TextSymbols(payload); linux = TextSymbols(kern); seen = False
    print(json.dumps(dict(firmware_sha256=sha(binfile), opensbi_elf_sha256=sha(payload), vmlinux_sha256=sha(kern))))
    for cycle, reg in samples(log):
        pc = reg['csr7b1']; prv = reg['csr7b0'] & 3; name = domain = None
        if fw_base <= pc < phys and prv == 3:
            domain = 'opensbi'; name = opensbi.lookup(pc)
        elif prv == 1 and virt <= pc < virt + len(image):
            domain = 'kernel-virtual'; name = linux.lookup(pc)
        elif prv == 1 and phys <= pc < phys + len(image):
            domain = 'kernel-physical'; name = linux.lookup(pc-phys+virt)
        print(json.dumps(dict(cycle=cycle, dpc=hex(pc), privilege=prv, satp=hex(reg['csr180']),
                              address_domain=domain, symbol=name, scause=hex(reg['csr142']),
                              sepc=hex(reg['csr141']), stval=hex(reg['csr143']), mcause=hex(reg['csr342']),
                              mepc=hex(reg['csr341']), mtval=hex(reg['csr343']),
                              x1=hex(reg['x1']), x2=hex(reg['x2']), x10=hex(reg['x10']), x11=hex(reg['x11'])))); seen = True
    if not seen:
        raise SystemExit('no complete resumed DMI sample yet; no PC evidence')


if __name__ == '__main__':
    main()
