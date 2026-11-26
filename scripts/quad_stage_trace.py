#!/usr/bin/env python3
"""Require all 1,024 retirements and a contiguous, same-PC, nine-stage RTL witness per hart."""
from collections import defaultdict
import re


def analyze(lines, low, high):
    if low%4 or high!=low+32: raise ValueError('expected eight aligned uncompressed instructions')
    seen=defaultdict(set); retire=[[] for _ in range(4)]; last=-1
    occupied=set(); speculative=set(); killed=set()
    for line in lines:
        m=re.fullmatch(r'TRACE (\d+) ([0-3]) ([0-8]) (\d+)( issue_killed)?',line)
        if not m:raise ValueError('malformed trace row')
        cycle,h,s,pc=map(int,m.groups()[:4]); flag=m[5] is not None
        if cycle<last or pc not in range(low,high,2) or (cycle,h,s) in occupied:raise ValueError('unknown PC, duplicate stage or unordered event')
        occupied.add((cycle,h,s));last=cycle
        if (pc-low)%4:
            # An RVC frontend may present the middle of an ADDI before a replay.
            # Do not discard these rows: require D -> I, affirmative issue kill,
            # and no valid X on the following edge. Never count them as witnesses.
            if s not in (4,5) or flag!=(s==5):raise ValueError('halfword PC issued, retired or missing kill evidence')
            (speculative if s==4 else killed).add((cycle,h,pc));continue
        if flag:raise ValueError('unexpected issue-kill marker')
        seen[h,s,pc].add(cycle)
        if s==8:retire[h].append((cycle,pc))
    if {(c+1,h,pc) for c,h,pc in speculative}!=killed or any((c+1,h,6) in occupied for c,h,pc in killed):
        raise ValueError('halfword decode/kill pair or following X bubble missing')
    result=[]
    for h,rows in enumerate(retire):
        if [pc for c,pc in rows]!=list(range(low,high,4))*32 or len({c for c,pc in rows})!=256:raise ValueError(f'hart {h}: missing, reordered or duplicated retirement')
        matched=[]
        for c,pc in rows:
            # Reject ambiguous matches to other dynamic executions of the same PC
            # within the nine-cycle witness; held or replayed values are not evidence.
            if all({t for t in range(c-8,c+1) if t in seen[h,s,pc]}=={c-8+s} for s in range(9)):
                matched.append(dict(pc=hex(pc),first_cycle=c-8,retire_cycle=c))
        if not matched:raise ValueError(f'hart {h}: no unambiguous consecutive nine-stage witness')
        result.append(dict(hart=h,retirements=len(rows),contiguous_witnesses=len(matched),first=matched[0]))
    return dict(halfword_decode_rows=len(speculative),halfword_issue_kills=len(killed),scope='Warm, aligned integer loop only; read-only samples after rising edges. Stalls, misses, RVC and traps are not assigned a fixed latency.',stages=['F0 request','F1','F2','A fetch queue head','D aligned instruction','I decoded instruction','X','M','W valid retirement'],harts=result)
