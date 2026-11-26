#!/usr/bin/env python3
"""Check the actual round-by-round SHA-256 output and the Linux PLIC serial row."""
import argparse,hashlib,json,re
from pathlib import Path


def command(nonce):
    if not re.fullmatch('[a-f0-9]{14}', nonce):raise ValueError('invalid nonce')
    return ('echo LINK_BEGIN_$((40+2))_TOKEN; cat /proc/interrupts; echo LINK_READY_TOKEN; for i in IDS; do IFS= read -r x || break; echo "$x" | sha256sum; echo LINK_ACK_${i}_TOKEN; done; echo LINK_AFTER_TOKEN; cat /proc/interrupts; echo LINK_END_$((20+22))_TOKEN').replace('TOKEN',nonce).replace('IDS',' '.join(str(i) for i in range(1,33)))


def exchange(raw, vectors, nonce):
    if not re.fullmatch('[a-f0-9]{14}',nonce) or len(vectors)!=32 or len(set(vectors))!=32 or not all(re.fullmatch('[a-f0-9]{256}',s) for s in vectors):raise ValueError('invalid host challenges')
    text=raw.decode('ascii').replace('\r\n','\n');rows=text.splitlines()
    if 'Kernel panic' in text or 'LINK_ABORT' in text.split('LINK_BEGIN_42_'+nonce+'\n')[-1]:raise ValueError('guest failed')
    def where(tag):
        hits=[i for i,row in enumerate(rows) if row in (tag,'# '+tag)]
        if len(hits)!=1:raise ValueError('missing or repeated '+tag)
        return hits[0]
    live,begin,ready,post,end=[where(k+nonce) for k in ('LINK_LIVE_42_','LINK_BEGIN_42_','LINK_READY_','LINK_AFTER_','LINK_END_42_')]
    if not live<begin<ready<post<end:raise ValueError('inconsistent shell transaction')
    cur=ready+1
    for i,line in enumerate(vectors,1):
        expect=[line,hashlib.sha256((line+'\n').encode()).hexdigest()+'  -',f'LINK_ACK_{i}_{nonce}']
        if rows[cur:cur+3]!=expect:raise ValueError('wrong echo, digest or acknowledgement at record '+str(i))
        cur+=3
    if cur!=post:raise ValueError('extra output in transaction')
    return rows[begin+1:ready],rows[post+1:end]


def inspect(raw,vectors,nonce):
    def serial(section):
        m=[int(x[1]) for s in section if (x:=re.fullmatch(r'\s*\d+:\s+(\d+)\s+SiFive PLIC\s+1\s+Edge\s+64000000\.serial\s*',s))]
        if len(m)!=1:raise ValueError('console interrupt row absent or ambiguous')
        return m[0]
    a,b=exchange(raw,vectors,nonce);before,after=serial(a),serial(b)
    if after<=before:raise ValueError('serial interrupt counter did not advance')
    return dict(records=len(vectors),ascii_payload_bytes=sum(map(len,vectors)),line_terminators=len(vectors),matching_sha256=32,plic_source=1,driver='64000000.serial',plic_serial_before=before,plic_serial_after=after,plic_serial_delta=after-before,console_sha256=hashlib.sha256(raw).hexdigest(),scope='single Linux console; includes input, terminal echo and output; not an RX-only IRQ count or peak link rate')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('local_result',type=Path,nargs='?');p.add_argument('--command',metavar='NONCE');a=p.parse_args()
    if a.command is not None:print(command(a.command));raise SystemExit(0)
    if not a.local_result:p.error('capture directory required');
    d=a.local_result
    print(json.dumps(inspect((d/'uart.txt').read_bytes(),(d/'vectors.txt').read_text().splitlines(),(d/'nonce.txt').read_text().strip()),indent=2))
