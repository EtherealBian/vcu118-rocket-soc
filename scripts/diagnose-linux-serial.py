#!/usr/bin/env python3
"""Explain a rejected 32-record Linux TTY capture; this tool cannot award a pass."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

spec=importlib.util.spec_from_file_location('link',Path(__file__).with_name('review-linux-serial.py'))
link=importlib.util.module_from_spec(spec);spec.loader.exec_module(link)


def explain(raw,vectors,nonce):
    try:
        link.inspect(raw,vectors,nonce)
    except ValueError as err:
        failure=str(err)
    else:
        raise ValueError('valid captures belong in the strict reviewer')
    if not re.fullmatch('wrong echo, digest or acknowledgement at record [1-9][0-9]*',failure):
        raise ValueError('not an isolated data-window rejection')
    rows=raw.decode('ascii').replace('\r\n','\n').splitlines()
    def loc(row):
        if rows.count(row)!=1:raise ValueError('no unique transaction boundary')
        return rows.index(row)
    start=loc('LINK_READY_'+nonce); failures=[]
    for i,vec in enumerate(vectors,1):
        end=loc('LINK_ACK_%d_%s'%(i,nonce)); frame=rows[start+1:end];start=end
        digest=lambda s:hashlib.sha256((s+'\n').encode()).hexdigest()+'  -'
        if frame==[vec,digest(vec)]:continue
        if not frame or not re.fullmatch('[0-9a-f]{64}  -',frame[-1]):raise ValueError('cannot identify the guest digest')
        pieces=[]; messages=0
        for row in frame[:-1]:
            # Optional hex echo prefix followed by an entire timestamped kernel line.
            k=re.fullmatch(r'([a-f0-9]*)\[\s*[0-9]+\.[0-9]+\] .+',row)
            if k:pieces.append(k[1]);messages+=1
            elif re.fullmatch('[0-9a-f]*',row):pieces.append(row)
            else:raise ValueError('unclassified data interleaving')
        echo=''.join(pieces)
        failures.append(dict(record=i,expected_chars=len(vec),echo_chars=len(echo),timestamped_kernel_lines=messages,
                             guest_digest_matches_full_line=frame[-1]==digest(vec),guest_digest_matches_reconstructed_echo=frame[-1]==digest(echo)))
    if loc('LINK_AFTER_'+nonce)!=start+1 or not failures:raise ValueError('wrong end boundary')
    return dict(strict_result='REJECTED',first_rejection=failure,affected=failures,console_sha256=hashlib.sha256(raw).hexdigest(),
                scope='Diagnosis only. A reconstructed echo never substitutes for strict byte/digest acceptance; does not identify the hardware or software cause.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);d=p.parse_args().capture
    print(json.dumps(explain((d/'uart.txt').read_bytes(),(d/'vectors.txt').read_text().splitlines(),(d/'nonce.txt').read_text().strip()),indent=2))
