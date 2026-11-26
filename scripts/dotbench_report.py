"""Check alternating measurement order and the 257-vector digest independently."""
import re
from statistics import median


def checksum():
    mask = 0xffffffff
    seed = 0x54321
    def draw():
        nonlocal seed
        seed ^= (seed << 13) & mask
        seed ^= seed >> 17
        seed ^= (seed << 5) & mask
        return seed
    pairs = [(0,0),(0x80808080,0x80808080),(0x7f7f7f7f,0x7f7f7f7f),
             (0x80808080,0x7f7f7f7f),(0x807fff01,0x017f80ff)]
    pairs += [(draw(),draw()) for _ in range(252)]
    def signed(x): return x-256 if x>=128 else x
    h=2166136261
    for a,b in pairs:
        total=sum(signed(x)*signed(y) for x,y in zip(a.to_bytes(4,'little'),b.to_bytes(4,'little')))
        h=((h^(total&mask))*16777619)&mask
    return h


def review(lines):
    if len(lines)!=10 or lines[0]!='DOTBENCH_START v1 vectors=257' or lines[-1]!='DOTBENCH_PASS vectors=257 rounds=4':
        raise ValueError('incomplete dot benchmark')
    digest=checksum(); windows=[]
    for i,line in enumerate(lines[1:-1]):
        r=i//2; kind='mmio' if (r^i)&1 else 'scalar'
        m=re.fullmatch(r'DOTBENCH (mmio|scalar) round=(\d+) checksum=(\d+) retired=(\d+) cycles=(\d+) mtime=(\d+)',line)
        if not m:raise ValueError('bad benchmark row')
        round_no,s,ins,cycles,mt=map(int,m.groups()[1:])
        if (m[1],round_no,s)!=(kind,r,digest) or not 0<ins<=cycles or mt<=0 or abs(mt*1000-cycles)>max(3000,cycles//100):
            raise ValueError('wrong order, vector checksum, or counters')
        windows.append(dict(kernel=kind,round=r,retired=ins,cycles=cycles,mtime=mt))
    mids={k:median(x['cycles'] for x in windows if x['kernel']==k) for k in ('scalar','mmio')}
    return dict(vectors_per_window=257,checksum_u32=digest,windows=windows,median_cycles=mids,mmio_to_scalar_elapsed_ratio=round(mids['mmio']/mids['scalar'],5))
