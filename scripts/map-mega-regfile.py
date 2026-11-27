#!/usr/bin/env python3
"""Map the two stock BOOM register files and their LVT alternatives in isolation.

A Yosys/ABC technology-map comparison, not Vivado utilization, placement, timing
or permission to change the sealed board image. All ports remain observable.
"""
import argparse
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
rf = runpy.run_path(str(HERE / 'check-mega-regfile.py'))


def table(text, top):
    marker = '=== ' + top + ' ==='
    if text.count(marker) != 1:
        raise ValueError('missing or ambiguous top statistics')
    block = text.split(marker)[1]
    if (not re.search(r'checking module ' + re.escape(top) + r'\.\.\nfound and reported 0 problems\.', block)
            or not all(re.search(r'^   Number of '+name+r':\s+0$', block, re.M)
                       for name in ('processes','memories'))):
        raise ValueError('incomplete or non-primitive mapping')
    cells = {}
    for k, n in re.findall(r'^     (\S+)\s+(\d+)$', block, re.M):
        if k in cells or not re.fullmatch(r'FDRE|LUT[1-6]|MUXF[78]|RAM128X1D', k):
            raise ValueError('unexpected cell type: '+k)
        cells[k] = int(n)
    totals = re.findall(r'^   Number of cells:\s+(\d+)$', block, re.M)
    if totals != [str(sum(cells.values()))] or not cells.get('FDRE') or not cells.get('LUT6'):
        raise ValueError('cell table is incomplete')
    return cells


def map_pair(kit, out, yosys):
    dig = rf['digest']
    if dig(kit/'CANDIDATE.sha256') != rf['SEAL']:
        raise ValueError('wrong four-wide kit')
    candidate = HERE.parent/'rtl/perf/vcu_lvt_regfile.v'
    version = subprocess.check_output([yosys, '-V'], text=True).strip()
    # Ubuntu Focal Yosys calls berkeley-abc on PATH. Pin the binaries in the
    # evidence rather than inferring tool identity from the report footer.
    abc = shutil.which('berkeley-abc')
    if not abc or version != 'Yosys 0.9 (git sha1 1979e0b)':
        raise ValueError('requires this experiment\'s Yosys 0.9 and berkeley-abc')
    av = subprocess.check_output([abc, '-c', 'version'], text=True).splitlines()[-1]
    if av != 'UC Berkeley, ABC 1.01':
        raise ValueError('unexpected ABC')
    out.mkdir(); profiles = []
    for d, nr, nw, expected, _ in rf['PROFILES']:
        original = kit/f'rtl/regfile_128x{d}.sv'
        if dig(original) != expected:
            raise ValueError('wrong stock RAM')
        item = dict(bits=d, readers=nr, writers=nw, stock_sha256=expected)
        for label in ('stock','lvt'):
            folder = out/f'{d}-{label}'; folder.mkdir()
            if label == 'stock':
                shutil.copyfile(original, folder/'stock.sv')
                (folder/'wrap.v').write_bytes(rf['wrapper'](d,nr,nw).encode())
                top = 'reference_wrapper'; cmd = 'read_verilog -sv stock.sv wrap.v\n'
            else:
                shutil.copyfile(candidate, folder/'lvt.v'); top = 'vcu_lvt_regfile'
                cmd = ('read_verilog -sv lvt.v\n'
                       f'chparam -set DATA {d} -set NR {nr} -set NW {nw} {top}\n')
            cmd += f'synth_xilinx -top {top} -family xcup -flatten\nselect -assert-none t:$mem t:$dff t:$lut\n'
            (folder/'map.ys').write_bytes(cmd.encode())
            with (folder/'yosys.log').open('wb') as log:
                subprocess.run([yosys,'-Q','-T','-s','map.ys'],cwd=folder,stdout=log,
                               stderr=subprocess.STDOUT,check=True,timeout=720)
            item[label] = table((folder/'yosys.log').read_text(), top)
        # 128 words per table. One copy of each writer bank per reader. The
        # register-based owner index needs ceil(log2(writers)) bits per word.
        if (item['stock'].get('RAM128X1D',0) or item['stock']['FDRE'] != 128*d
                or item['lvt'].get('RAM128X1D') != d*nr*nw
                or item['lvt']['FDRE'] != 128*(nw-1).bit_length()):
            raise ValueError('unexpected mapping of storage or owner table')
        profiles.append(item)
    return dict(scope='Isolated Yosys/ABC xcup technology mapping. Primitive counts, not occupied LUT sites, vendor timing, full-core synthesis or a benchmark.',
                board_input_seal=rf['SEAL'],candidate_sha256=dig(candidate),yosys=version,
                yosys_binary_sha256=dig(Path(yosys)),abc=av,abc_binary_sha256=dig(Path(abc)),profiles=profiles)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--yosys',default='yosys');a=p.parse_args()
    tool=shutil.which(a.yosys)
    if not tool: p.error('Yosys not found')
    result=map_pair(a.kit.resolve(),a.out.resolve(),str(Path(tool).absolute()))
    (a.out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('FOUR_ISOLATED_MAPPINGS_COMPLETE_NOT_TIMING')
