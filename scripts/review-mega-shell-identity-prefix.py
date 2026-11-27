#!/usr/bin/env python3
"""Review the stock Linux identity exchange only; a growing trace is not a completed benchmark."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mega_linux_shell_review as shell


def need(check, why):
    if not check: raise ValueError(why)


def digest(data): return sha256(data).hexdigest()


def inspect(raw, events, nonce):
    cmd = shell.commands(nonce)[:2]
    ref = json.loads((HERE.parent/'docs/perf-mega175-linux-entry.json').read_bytes())
    end = ('\r\nCM_MACHINE_END_42_'+nonce+'\r\n').encode('ascii'); n = raw.find(end)
    need(n >= 0, 'no complete independent identity reply')
    uart = raw[:n+len(end)]
    match = re.search(rb'^SHELL_REPLY tick=\d+ step=2\n',events,re.M)
    need(match, 'no complete end of second wire exchange'); wire = events[:match.end()]
    rows = uart.decode('ascii').split('\r\n')[:-1]
    need(not any('\n' in v or '\r' in v for v in rows), 'unexpected line ending')
    init = b'VCU118_INITRAMFS_READY\r\n'; n = uart.find(init)+len(init)
    need(n==6405 and digest(uart[:n])=='3d69df6a046fc517ce8566d9c94ff253717ab505950c8d2d8631336ecfcb08ab', 'changed stock init prefix')
    def locate(s):
        hits = [i for i,v in enumerate(rows) if re.fullmatch(s,v)]
        need(len(hits)==1,'missing or ambiguous identity phase'); return hits[0]
    positions = [locate(r'VCU118_INITRAMFS_READY'),locate(r'SOC_CHECK_PASS bytes=16777216 passes=1 elapsed_s=\d+'),
                 locate(r'LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d'),
                 locate(r'BusyBox v1\.36\.1 .* built-in shell \(ash\)'),locate(re.escape('# '+cmd[0])),
                 locate(re.escape('CM_LIVE_42_'+nonce)),locate(re.escape('# '+cmd[1])),
                 locate(re.escape('CM_BOOT_'+nonce+'_42_'+nonce)),locate(re.escape('CM_MACHINE_END_42_'+nonce))]
    need(positions==sorted(set(positions)) and positions[-1]==len(rows)-1,'misordered phases')
    need(not any(re.search(r'Kernel panic|Oops:|_FAIL(?:ED)?\b',v) for v in rows) and
         not any(re.search(r'not found|No such file',v) for v in rows[positions[4]:]),'guest failure before cut')
    shell.machine.inspect(rows,positions[6],len(rows),nonce,nonce,shell.machine.MEGA_SEAL)
    need([v for v in rows[positions[7]+1:positions[8]] if re.match(r'mmu\s*:',v)]==['mmu\t\t: sv39'],'unexpected MMU')
    split = re.search(rb'^ENTRY_PREFIX bytes=(\d+)\n',wire,re.M)
    need(split and digest(wire[:split.start()])==ref['evidence']['boot.events'] and
         digest(uart[:int(split[1])])==ref['evidence']['boot.uart'], 'different reset/entry evidence')
    stamp = ref['witness']['observation_end_tick']; transactions=[]; progress=[]; spi=None
    old=(ref['witness']['backing_tl_reads'],ref['witness']['backing_tl_writes'])
    for line in wire[split.end():].decode('ascii').splitlines():
        p=re.fullmatch(r'PROGRESS cycles=(\d+) reads=(\d+) writes=(\d+)',line)
        sel=re.fullmatch(r'POST_ENTRY_SPI_SELECT tick=(\d+)',line)
        x=re.fullmatch(r'SHELL_(TX|REPLY) tick=(\d+) (step=\d+(?: bytes=\d+)?)',line)
        if p:
            t,a,b=map(int,p.groups()); need(a>=old[0] and b>=old[1],'backing counters decreased'); old=(a,b);progress.append(t)
        elif sel:
            t=int(sel[1]); need(spi is None and t>ref['witness']['observation_end_tick'],'repeated/early first select'); spi=t
        else:
            need(x,'unrecognized wire event'); t=int(x[2]); transactions.append((x[1],x[3],t))
        need(stamp<=t<2400000000,'event time out of bounds'); stamp=t
    want=[]
    for i,c in enumerate(cmd,1): want.extend([('TX',f'step={i} bytes={len(c)+1}'),('REPLY',f'step={i}')])
    need([(a,b) for a,b,_ in transactions]==want and progress==list(range(45000000,stamp,5000000)), 'incomplete progress or command sequence')
    ticks=[t for _,_,t in transactions]
    need(ticks[2]>ticks[1] and all(ticks[2*j+1]-ticks[2*j]>=(4+24*(len(c)+1)-14)*1519 for j,c in enumerate(cmd)), 'impossible RX/TX time')
    return dict(scope='Stock four-wide ChipTop RTL, from reset through two interactive shell replies. No benchmark execution attested.',
                online_cpu=0,hart=0,uarch='ucb-bar,boom0',mmu='sv39',dt_properties_checked=3,ram_check_bytes=16777216,oscheck_rounds=64,
                shell_tx_ticks=ticks[::2],shell_reply_ticks=ticks[1::2],uart_prefix_bytes=len(uart),uart_prefix_sha256=digest(uart),
                events_prefix_bytes=len(wire),events_prefix_sha256=digest(wire))


def controls(raw,events,nonce):
    bad=[(raw.replace(('\r\nCM_LIVE_42_'+nonce).encode(),('\r\n'+shell.commands(nonce)[0]).encode()),events),
         (raw.replace(b'262a28db',b'162a28db'),events), (raw,events.replace(b' step=2\n',b' step=1\n')),
         (raw.replace(('CM_MACHINE_END_42_'+nonce+'\r\n').encode(),('CM_MACHINE_END_42_'+nonce+'\r').encode()),events),
         (raw,events.replace(b'cycles=45000000 ',b'cycles=45000001 ')),(raw,events.replace(b'bytes=327',b'bytes=326'))]
    for a,b in bad:
        need((a,b)!=(raw,events),'broken negative control')
        try: inspect(a,b,nonce)
        except ValueError: continue
        raise ValueError('false pass on corrupted shell exchange')
    return len(bad)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('release',type=Path);p.add_argument('--pid',type=int);a=p.parse_args()
    d=a.run.resolve(strict=True); rel=a.release.resolve(strict=True); pins=json.loads((d/'inputs.json').read_bytes())
    ref=json.loads((HERE.parent/'docs/perf-mega175-linux-entry.json').read_bytes()); model=d/'model'; fw=rel/'fw_payload.bin'
    expected={**ref['inputs'],**ref['models']['stock']}; expected.pop('crc.frame');expected.pop('model')
    need(all(pins.get(k)==v for k,v in expected.items()),'not the stock run manifest')
    for path in [model,fw,rel/'Image',rel/'coremark-g15-gc-lto-ooo-strict.elf',d/'boot.cpp',d/'prefix.frame',d/'commands.txt',d/'nonce',
                 HERE/'mega_linux_shell_review.py',HERE/'linux_machine_witness.py',HERE/'test-mega-linux-shell.py',HERE.parent/'tests/mega_linux_shell.hpp']:
        need(digest(path.read_bytes())==pins[path.name], 'different stock shell input: '+path.name)
    if a.pid is not None:
        proc=Path('/proc')/str(a.pid)
        need((proc/'exe').samefile(model) and (proc/'fd/1').samefile(d/'linux.uart') and (proc/'fd/2').samefile(d/'linux.events'),'not this live capture')
        # Do not print the private challenge, argument list or host paths.
        argv=(proc/'cmdline').read_bytes().rstrip(b'\0').decode().split('\0'); need(len(argv)==6 and argv[1]=='valid' and Path(argv[2]).samefile(fw) and
             Path(argv[3]).samefile(d/'prefix.frame') and Path(argv[4]).samefile(d/'commands.txt') and argv[5]==(d/'nonce').read_text().strip(),'wrong model stimulus')
    nonce=(d/'nonce').read_text().strip(); need((d/'commands.txt').read_bytes()==('\n'.join(shell.commands(nonce))+'\n').encode(),'not the qualified commands')
    raw=(d/'linux.uart').read_bytes(); events=(d/'linux.events').read_bytes()
    result=inspect(raw,events,nonce);result.update(rejected_controls=controls(raw,events,nonce),model_sha256=pins['model'],
                                                   stock_kit_sha256=pins['CANDIDATE.sha256'],inputs_sha256=digest((d/'inputs.json').read_bytes()))
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
