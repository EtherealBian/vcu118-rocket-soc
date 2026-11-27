#!/usr/bin/env python3
"""Compare the first supervisor-mode instruction window, not a complete Linux boot.

The missing firmware entry prefix is loaded through the ROM UART with a second
one-bit CRC control. Only the raw firmware path is exercised, not the LZ4 U5
upload, physical DDR, Linux userspace, or a timed CoreMark workload.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import zlib

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))
from uart_frame import encode
PROBE=runpy.run_path(str(HERE/'check-mega-regfile-chiptop.py'))

def h(path):return sha256(path.read_bytes()).hexdigest()

# Linker symbols from the aligned release's vmlinux, relative to _start.
# __initramfs_size addresses an eight-byte variable, not the size itself.
INITRD_START = 0x1b2b48
INITRD_SIZE_WORD = 0x2182d8
STRICT = b'bin/coremark-g15-gc-lto-ooo-strict'


def embedded_benchmark(image, expected, start=INITRD_START, size_word=INITRD_SIZE_WORD):
    """Read one gzip/newc archive in memory; never extract paths onto the host."""
    if not (0 <= start < size_word <= len(image)-8):
        raise ValueError('initramfs symbols outside Image')
    n = int.from_bytes(image[size_word:size_word+8], 'little')
    if not 0 < n <= size_word-start:
        raise ValueError('initramfs extent outside Image')
    stream = image[start:start+n]
    z = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        archive = z.decompress(stream, 2**20)  # release-specific upper bound
    except zlib.error as e:
        raise ValueError('invalid initramfs gzip') from e
    if not z.eof or z.unused_data or z.unconsumed_tail:
        raise ValueError('incomplete, oversized or concatenated initramfs')
    offset = 0
    names = set()
    while True:
        hdr = archive[offset:offset+110]
        if not re.fullmatch(rb'070701[0-9A-Fa-f]{104}', hdr):
            raise ValueError('expected a newc header')
        _, mode, uid, gid, links, _, size, _, _, _, _, namesize, check = (
            int(hdr[i:i+8], 16) for i in range(6,110,8))
        a = offset + 110
        b = a + namesize
        c = (b+3) & ~3
        end = c + size
        offset = (end+3) & ~3
        if (check or not 2 <= namesize <= 4096 or offset > len(archive) or
                archive[b-1] or any(archive[b:c]) or any(archive[end:offset])):
            raise ValueError('invalid newc bounds, terminator or padding')
        name = archive[a:b-1]
        if name == b'TRAILER!!!':
            if size or any(archive[offset:]):
                raise ValueError('extra data after archive trailer')
            break
        if b'\0' in name or name in names or any(k in (b'',b'.',b'..') for k in name.split(b'/')):
            raise ValueError('ambiguous initramfs name')
        names.add(name)
        if name == b'bin' and (mode != 0o40755 or uid or gid or size):
            raise ValueError('expected real bin directory')
        if name == STRICT and ((mode,uid,gid,links) != (0o100755,0,0,1) or archive[c:end] != expected):
            raise ValueError('strict benchmark is not the expected regular executable')
    if not {b'bin', STRICT} <= names:
        raise ValueError('missing strict benchmark in initramfs')
    return dict(gzip_offset=start, gzip_bytes=n, newc_bytes=len(archive), entries=len(names),
                member=STRICT.decode('ascii'), elf_bytes=len(expected), elf_sha256=sha256(expected).hexdigest())

def inspect(crc,crc_uart,events,uart,preload):
    if crc_uart!=b'UART5_READY v1\r\nUART5_STOP CRC\r\n':raise ValueError('bad frame not stopped by ROM')
    neg=re.fullmatch(r'BAD_CRC_STOP tick=(\d+) quiet_bits=20\n',crc)
    if not neg or not 24*10*1519<int(neg[1])<2000000:raise ValueError('bad CRC event')
    lines=uart.decode('ascii').replace('\r\n','\n').split('\n')
    if lines[:2]!=['UART5_READY v1','UART5_HANDOFF'] or len([s for s in lines if 'UART5_' in s])!=2:raise ValueError('wrong ROM epoch')
    patterns=[r'OpenSBI v1\.5',r'Platform HART Count\s+: 1',r'Platform Timer Device\s+: aclint-mtimer @ 175000Hz',
              r'Domain0 Boot HART\s+: 0',r'Domain0 Next Address\s+: 0x0*80200000',r'Domain0 Next Mode\s+: S-mode']
    positions=[]
    for pat in patterns:
        indices=[i for i,t in enumerate(lines) if re.fullmatch(pat,t)]
        if len(indices)!=1:raise ValueError('missing or repeated OpenSBI marker: '+pat)
        positions.extend(indices)
    if positions!=sorted(positions) or positions[0]<=1:raise ValueError('OpenSBI order')
    rows=[];progress=[];timeline=[]
    for line in events.splitlines():
        timestamp=re.search(r' (?:tick|cycles)=(\d+)(?: |$)',line)
        if not timestamp:raise ValueError('event without a model clock')
        timeline.append(int(timestamp[1]))
        m=re.fullmatch(r'PROGRESS cycles=(\d+) reads=(\d+) writes=(\d+)',line)
        if m:progress.append(tuple(map(int,m.groups())))
        else:rows.append(line)
    if len(rows)!=4 or timeline!=sorted(timeline):raise ValueError('extra, missing or out-of-order model event')
    def unique(pattern):
        matches=[m for s in rows if (m:=re.fullmatch(pattern,s))]
        if len(matches)!=1:raise ValueError('missing or repeated architectural event')
        return list(map(int,matches[0].groups()))
    wire,n=unique(r'ROM_HANDOFF tick=(\d+) wire=24 backing_preloaded=(\d+) edge_intervals=9 ticks_per_bit=1519')
    get,size=unique(r'KERNEL_ENTRY_TL_GET tick=(\d+) bytes=(\d+)')
    mret,=unique(r'MRET_KERNEL tick=(\d+) mepc=0x80200000 prv=3->1 mpp=1 satp_mode=0')
    end,count,reads,writes=unique(r'ENTRY_WITNESS tick=(\d+) s_arch_retired=(\d+) reads=(\d+) writes=(\d+)')
    if (n!=preload or not 24*10*1519<wire<min(mret,get)<=max(mret,get)<end<80000000 or not 256<=count<=259 or
            size not in (8,16,32,64) or min(reads,writes)<=0 or not rows[0].startswith('ROM_HANDOFF ') or not rows[-1].startswith('ENTRY_WITNESS ')):
        raise ValueError('kernel entry or supervisor retirement boundaries')
    # The external read might be speculative: allow it on either side of MRET,
    # never substitute it alone for the registered privilege/retirement witness.
    if ([v[0] for v in progress]!=list(range(5000000,end,5000000)) or
            any(a>b for j in (1,2) for a,b in zip([v[j] for v in progress],[v[j] for v in progress][1:]+[reads if j==1 else writes]))):
        raise ValueError('model progress sequence')
    return dict(negative_crc_stop_tick=int(neg[1]),valid_rom_handoff_tick=wire,mret_tick=mret,entry_address='0x80200000',
                entry_tl_get_tick=get,entry_tl_get_bytes=size,observation_end_tick=end,supervisor_arch_commits=count,
                backing_tl_reads=reads,backing_tl_writes=writes,entry_frame_bytes=24,backing_preloaded_bytes=n)

def review(role,kit,pins,d,release):
    raw=release/'fw_payload.bin';image=release/'Image';bench=release/'coremark-g15-gc-lto-ooo-strict.elf'
    results=json.loads((ROOT/'docs/perf-mega175-regfile-chiptop.json').read_bytes());row=results['models'][role]
    pin=PROBE['model'](role,kit,pins);paths={};hashes={}
    for line in (d/'inputs.sha256').read_text().splitlines():
        dig,name=line.split('  ',1);p=(ROOT/name).resolve(strict=True)
        if p.name in paths or h(p)!=dig:raise ValueError('changed inputs or duplicate basename')
        paths[p.name]=p;hashes[p.name]=dig
    paths0=[d/k for k in ('model','prefix.frame','crc.frame')]+[kit/'CANDIDATE.sha256',pins/'result.json',raw,image,bench,ROOT/'tests/mega_linux_entry.cpp',ROOT/'tests/rocket_chiptop.cpp',*(ROOT/'tests').glob('chiptop_*.hpp')]
    obj=paths['VChipTop__ALL.a'].parent;paths0.extend(obj/k for k in ('VChipTop__ALL.a','VChipTop___024root.h','verilated.o','verilated_threads.o'))
    if (paths!={p.name:p for p in paths0} or hashes['VChipTop__ALL.a']!=row['model_archive_sha256'] or hashes['CANDIDATE.sha256']!=row['kit_seal'] or
            pin['inputs']['VChipTop__ALL.a']!=hashes['VChipTop__ALL.a'] or pin['rom_dtb_sha256']!=results['rom_dtb_sha256']):raise ValueError('unbound executable/kit')
    subprocess.run([sys.executable,str(HERE/'check-model-kit.py'),str(obj),str(kit)],check=True,stdout=subprocess.DEVNULL)
    fw=raw.read_bytes();im=image.read_bytes();source=json.loads((ROOT/'docs/linux-align-rocket-boot.json').read_bytes())['packed_stage']; profile,=[v for v in json.loads((ROOT/'docs/linux-align-code.json').read_bytes())['profiles'] if v['profile']=='g15-gc-lto-ooo-strict']
    good=encode(fw[:8]);bad=bytearray(good);bad[12]^=1
    if (h(raw)!=source['raw_sha256'] or len(fw)!=source['raw_bytes'] or fw.count(im)!=1 or fw.find(im)!=0x200000 or im[48:56]!=b'RISCV\0\0\0' or profile['elf_sha256']!=h(bench) or
            (d/'crc.frame').read_bytes()!=bad or (d/'prefix.frame').read_bytes()!=good):raise ValueError('different firmware, kernel, ELF or ROM fault')
    embedded=embedded_benchmark(im,bench.read_bytes())
    witness=inspect((d/'crc.events').read_text(),(d/'crc.uart').read_bytes(),(d/'boot.events').read_text(),(d/'boot.uart').read_bytes(),len(fw)-8)
    evidence={n:h(d/n) for n in ('boot.events','boot.uart','crc.events','crc.uart')}
    return dict(role=role,hashes=hashes,evidence=evidence,witness=witness,embedded=embedded)

def pair(a,b):
    if (a['role'],b['role'])!=('stock','lvt') or any(a['hashes'][n]==b['hashes'][n] for n in ('model','CANDIDATE.sha256','VChipTop__ALL.a')):raise ValueError('not different builds')
    identical=('fw_payload.bin','Image','coremark-g15-gc-lto-ooo-strict.elf','prefix.frame','crc.frame','mega_linux_entry.cpp','rocket_chiptop.cpp')
    if any(a['hashes'][k]!=b['hashes'][k] for k in identical) or a['witness']!=b['witness'] or a['evidence']!=b['evidence'] or a['embedded']!=b['embedded']:raise ValueError('different boot image or changed observed behavior')
    return dict(scope='Two functional BOOM models. Unpacked OpenSBI+Linux, first 8 bytes received via ROM pins, remaining bytes preloaded in behavioral TL RAM. Ends after an M-to-S transition and a short retirement window. No full-stage upload/decompression, userspace, FPGA or board score.',
                inputs={k:a['hashes'][k] for k in identical},models={r['role']:{k:r['hashes'][k] for k in ('CANDIDATE.sha256','VChipTop__ALL.a','model','VChipTop___024root.h')} for r in (a,b)},evidence=a['evidence'],embedded_benchmark=a['embedded'],witness=a['witness'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('stock_kit','stock_pins','stock_run','lvt_kit','lvt_pins','lvt_run','release'):p.add_argument(arg,type=Path)
    a=p.parse_args();args=[v.resolve(strict=True) for v in vars(a).values()];print(json.dumps(pair(review('stock',*args[:3],args[-1]),review('lvt',*args[3:6],args[-1])),indent=2))
