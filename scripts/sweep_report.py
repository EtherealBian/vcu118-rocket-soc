"""Validate every reported milestone in order, separately from the guest PASS banner."""
import re


def review(lines):
    expected_bytes=254*(8<<20)
    if len(lines)!=18 or lines[0]!='VCU118_SWEEP_START v1 block_mib=8 blocks=254' or lines[-1]!=f'VCU118_SWEEP_PASS bytes={expected_bytes} passes=2':
        raise ValueError('sweep envelope incomplete')
    phases=[]; at=1
    for p in (0,1):
        for kind in ('write','read'):
            last=0
            for blocks in (64,128,192,254):
                m=re.fullmatch(fr'SWEEP pass={p} {kind} blocks={blocks} ticks=([1-9]\d*)',lines[at]); at+=1
                if not m or int(m[1])<=last:raise ValueError('sweep coverage or timer order')
                last=int(m[1])
            phases.append(dict(pattern=p,operation=kind,mtime_ticks=last))
    return dict(unique_bytes=expected_bytes,word_bytes=8,patterns=['address-derived','bitwise complement'],excluded_ranges_inclusive=['0x80000000..0x807fffff','0x8f800000..0x8fffffff'],phases=phases)
