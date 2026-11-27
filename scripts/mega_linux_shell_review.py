"""Review a reset-to-userspace simulation. This module cannot register a board score."""
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import linux_machine_witness as machine

CRC = runpy.run_path(str(HERE/'derive-target-length-crcs.py'))
CM = CRC['CM']
PROFILE = 'g15-gc-lto-ooo-strict'
CRC4 = {'performance':'0x9f95','validation':'0x19d9'}


def commands(nonce):
    bench = CM['command'](nonce,4,PROFILE)  # checks nonce; includes hash + exact args
    paths = ' '.join(machine.SYSFS+p for p in machine.PROPERTIES)
    return [f'echo CM_LIVE_$((40+2))_{nonce}',
            f'echo CM_BOOT_{nonce}_$((40+2))_{nonce}; cat /sys/devices/system/cpu/online /proc/cpuinfo; '
            f'sha256sum {paths}; echo CM_MACHINE_END_$((40+2))_{nonce}', bench]


def one(rows, value):
    hits = [i for i,v in enumerate(rows) if v in (value, '# '+value)]
    if len(hits)!=1:
        raise ValueError('missing or ambiguous row: '+value)
    return hits[0]


def benchmark(rows, nonce, digest):
    cmd = one(rows,commands(nonce)[2]); prev = one(rows,digest+'  '+CM['binary'](PROFILE))
    if cmd>=prev:
        raise ValueError('ELF must be hashed by this command')
    result = {}
    for kind in CM['CASES']:
        a = one(rows,f'CM_{kind}_42_{nonce}'); b = one(rows,f'CM_{kind}_RC_0_{nonce}')
        if not prev<a<b:
            raise ValueError('invalid benchmark boundaries')
        region = rows[a+1:b]; field = CRC['field']
        if (field(region,'Compiler version') != CM['expected_compiler'](PROFILE) or
                ' '.join(field(region,'Compiler flags').split()) != CM['PROFILES'][PROFILE][1]):
            raise ValueError('different compiler or flags')
        result[kind] = CRC['crc']('\n'.join(region),kind,4)
        if result[kind] != CRC4[kind]:
            raise ValueError('wrong four-iteration final CRC')
        prev = b
    if not prev<one(rows,'CM_DONE_42_'+nonce)==len(rows)-1:
        raise ValueError('missing final reply or extra data')
    return result


def inspect(raw, events, nonce):
    ref = json.loads((ROOT/'docs/perf-mega175-linux-entry.json').read_bytes())
    tail = events.splitlines(keepends=True)
    splits = [i for i,v in enumerate(tail) if v.startswith('ENTRY_PREFIX ')]
    if len(splits)!=1:
        raise ValueError('missing or repeated original entry witness')
    cut = splits[0]; m = re.fullmatch(r'ENTRY_PREFIX bytes=(\d+)\n',tail[cut])
    if (not m or not 0<int(m[1])<len(raw) or sha256(raw[:int(m[1])]).hexdigest()!=ref['evidence']['boot.uart'] or
            sha256(''.join(tail[:cut]).encode()).hexdigest()!=ref['evidence']['boot.events']):
        raise ValueError('original reset, OpenSBI or kernel entry diverged')
    text = raw.decode('ascii').replace('\r',''); rows = text.splitlines()
    if re.search(r'Kernel panic|Oops:|_FAIL(?:ED)?\b|Cannot validate operation',text):
        raise ValueError('guest failure')
    def unique(pattern):
        hits=[i for i,x in enumerate(rows) if re.fullmatch(pattern,x)]
        if len(hits)!=1:
            raise ValueError('missing/duplicate boot phase '+pattern)
        return hits[0]
    cmd = commands(nonce)
    order = [unique(r'(?:\[\s*[0-9.]+\] )?Linux version 6\.6\.65 .*'),one(rows,'VCU118_INITRAMFS_READY'),
             unique(r'SOC_CHECK_PASS bytes=16777216 passes=[1-9]\d* elapsed_s=\d+'),
             one(rows,'LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d'),
             unique(r'BusyBox v1\.36\.1 .* built-in shell \(ash\)'),one(rows,cmd[0]),one(rows,'CM_LIVE_42_'+nonce),
             one(rows,cmd[1]),one(rows,f'CM_BOOT_{nonce}_42_{nonce}'),one(rows,'CM_MACHINE_END_42_'+nonce),one(rows,cmd[2])]
    if order!=sorted(order):
        raise ValueError('misordered boot or shell command')
    # A normal non-EFI kernel prints 'efi: UEFI not found.' at boot. Only
    # command-epoch lookup failures invalidate these shell probes.
    if any(re.search(r'not found|No such file',row) for row in rows[order[5]:]):
        raise ValueError('shell command or requested property missing')
    machine.inspect(rows,order[7],order[-1],nonce,nonce,machine.MEGA_SEAL)
    result = benchmark(rows,nonce,ref['embedded_benchmark']['elf_sha256'])
    shell_events=[]; tick=ref['witness']['observation_end_tick']; progress=[]; spi=None
    for line in tail[cut+1:]:
        match = re.fullmatch(r'PROGRESS cycles=(\d+) reads=(\d+) writes=(\d+)\n',line)
        if match:
            now=int(match[1]); progress.append(tuple(map(int,match.groups())))
        elif (select:=re.fullmatch(r'POST_ENTRY_SPI_SELECT tick=(\d+)\n',line)):
            now=int(select[1]);
            if spi is not None or now<=ref['witness']['observation_end_tick']:
                raise ValueError('invalid first post-entry SPI select')
            spi=now
        else:
            m=re.fullmatch(r'SHELL_(TX|REPLY|WIRE_DONE) tick=(\d+)(.*?)\n',line)
            if not m:
                raise ValueError('unexpected model event')
            now=int(m[2]); shell_events.append((m[1],now,m[3]))
        if now<tick or now>=2400000000:
            raise ValueError('trace outside model horizon')
        tick=now
    want=[]
    for j,line in enumerate(cmd,1):
        want.extend([('TX',f' step={j} bytes={len(line)+1}'),('REPLY',f' step={j}')])
    if [(k,s) for k,t,s in shell_events]!=want+[('WIRE_DONE','')] or shell_events[-2][1]!=shell_events[-1][1]:
        raise ValueError('incomplete wire exchange')
    for j,line in enumerate(cmd):
        if shell_events[2*j+1][1]-shell_events[2*j][1] < (4+24*(len(line)+1)-14)*1519:
            raise ValueError('impossible wire reply latency')
    if ([p[0] for p in progress]!=list(range(45000000,tick,5000000)) or
            any(any(x>y for x,y in zip(series,series[1:])) for series in
                ([ref['witness'][key]]+[p[col] for p in progress] for col,key in ((1,'backing_tl_reads'),(2,'backing_tl_writes'))))):
        raise ValueError('incomplete progress record')
    return dict(scope='Stock functional ChipTop with preloaded external TL RAM; Linux four-iteration CRC diagnostic only, not a board result.',
                online_hart=0,contexts=1,buffer_bytes=2000,iterations_per_seed=4,final_crcs=result,
                first_post_entry_spi_select_tick=spi,shell_done_model_tick=tick,uart_sha256=sha256(raw).hexdigest(),events_sha256=sha256(events.encode()).hexdigest())
