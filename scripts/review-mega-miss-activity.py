"""Validate one trace row per pre-edge tick and separate Boolean sensitivity from actual use."""
from collections import Counter
from hashlib import sha256
import re


def need(condition, msg):
    if not condition: raise ValueError(msg)


def decode(raw):
    need(len(raw)==22,'partial trace row')
    a,b,c,o=[int.from_bytes(raw[i:i+5],'little') for i in (0,5,10,15)]
    m,s=raw[20:22]
    need(m<2 and s in (0,9,10,11,12) and (b|c|o)<1<<39,'out-of-range fields')
    need(not (b&c) and o==(b|(c if m else 0)),'observed move mask differs')
    need(bool(c&256)==bool(s and a&(1<<s)),'slot 8 source mismatch')
    need(not c or a,'destination lacks sensitive source')
    return a,b,c,o,m,s


def rejects(call):
    try: call()
    except ValueError: return
    raise ValueError('negative control was accepted')


def review(d, ref):
    dig={k:sha256((d/k).read_bytes()).hexdigest() for k in ('uart','events','pc')}
    need(dig==ref['evidence_sha256'],'architectural trace no longer agrees byte-for-byte')
    ev=(d/'events').read_text(); m=re.findall(r'^WINDOW hot=(\d+) .* fences=([\d,]+)$',ev,re.M)
    need(len(m)==1 and int(m[0][0])==ref['arch_instructions'],'wrong retirement window')
    ticks=list(map(int,m[0][1].rstrip(',').split(','))); lengths=[y-x for x,y in zip(ticks,ticks[1:])]
    raw=(d/'moves.bin').read_bytes()
    need(lengths==ref['by_round_cycles'] and len(raw)==22*sum(lengths)==22*ref['cycles'],'missing cycles/rounds')
    bad=bytearray(raw[:22]); bad[15]^=1; rejects(lambda:decode(bad))
    rejects(lambda:decode(raw[:21])); bad=bytearray(raw[:22]); bad[21]=8; rejects(lambda:decode(bad))
    off=0; rows=[]; total_dest=[0]*39; total_src=[0]*40; s8_sources=[0]*4
    for count in lengths:
        stats=Counter({k:0 for k in ('cycles','lsu_miss_cycles','resident_sensitive_cycles','miss_and_resident_sensitive_cycles',
                          'move_sensitive_cycles','miss_and_move_sensitive_cycles','miss_and_move_sensitive_destinations',
                          'slot8_sensitive_cycles','miss_and_slot8_sensitive_cycles','slot9_to_8_sensitive_cycles','miss_and_slot9_to_8_sensitive_cycles')})
        for _ in range(count):
            a,_,c,_,m,s=decode(raw[off:off+22]); off+=22
            stats['cycles']+=1; stats['lsu_miss_cycles']+=m
            if a:
                stats['resident_sensitive_cycles']+=1
                if m:
                    stats['miss_and_resident_sensitive_cycles']+=1
                    while a:
                        bit=a & -a; total_src[bit.bit_length()-1]+=1; a-=bit
            if c:
                stats['move_sensitive_cycles']+=1
                if c&256:
                    stats['slot8_sensitive_cycles']+=1; stats['slot9_to_8_sensitive_cycles']+=int(s==9)
                    if m:
                        stats['miss_and_slot8_sensitive_cycles']+=1; stats['miss_and_slot9_to_8_sensitive_cycles']+=int(s==9); s8_sources[s-9]+=1
                if m:
                    stats['miss_and_move_sensitive_cycles']+=1
                    while c:
                        bit=c & -c; total_dest[bit.bit_length()-1]+=1; c-=bit
                        stats['miss_and_move_sensitive_destinations']+=1
        rows.append(dict(stats))
    totals={k:sum(x[k] for x in rows) for k in rows[0]}
    need(off==len(raw) and sum(total_dest)==totals['miss_and_move_sensitive_destinations'] and
         sum(s8_sources)==total_dest[8] and s8_sources[0]==totals['miss_and_slot9_to_8_sensitive_cycles'],'accounting')
    return dict(totals=totals,by_round=rows,actual_miss_sensitive_resident_counts=total_src,
                actual_miss_sensitive_move_counts=total_dest,actual_slot8_by_source_9_to_12=s8_sources,
                architectural_evidence_sha256=dig,moves_sha256=sha256(raw).hexdigest(),negative_controls_rejected=3)
