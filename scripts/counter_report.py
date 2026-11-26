"""Validate ordered, fixed-instruction M-mode counter windows, not an ISA benchmark."""
import re


def review(lines):
    n = 131072
    spec = [('chain-add', n, 3*n+1), ('load-use', 3*n, 4*n+1), ('branch-alt', n, 4*n+n//2+1)]
    if len(lines) != 11 or lines[0] != 'VCU118_COUNTER_START v1 n=131072' or lines[-1] != 'VCU118_COUNTER_PASS kernels=3 rounds=3':
        raise ValueError('missing microkernel epoch or data')
    rows=[]
    for i,s in enumerate(lines[1:-1]):
        name,total,expected = spec[i%3]; r=i//3
        m=re.fullmatch(r'COUNTER ([a-z-]+) round=(\d+) result=(\d+) retired=(\d+) cycles=(\d+) mtime=(\d+)',s)
        if not m:raise ValueError('bad counter record')
        got,value,ins,cyc,ticks=map(int,m.groups()[1:]);
        if (m[1],got,value,ins)!=(name,r,total,expected):raise ValueError('wrong window, arithmetic result, or retired count')
        # MTIME brackets the function, slightly wider than the two CSR reads. Both
        # counters have a common clock source; this is a ratio check, not a frequency meter.
        if not ins<=cyc or ticks<=0 or abs(ticks*1000-cyc)>max(3000,cyc//100):raise ValueError('counter/mtime agreement failed')
        rows.append(dict(kernel=name,round=r,retired=ins,cycles=cyc,mtime_ticks=ticks,cpi=round(cyc/ins,5)))
    return rows
