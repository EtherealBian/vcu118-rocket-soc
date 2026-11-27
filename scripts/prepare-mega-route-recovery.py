#!/usr/bin/env python3
"""Seal a fresh timing-recovery kit; rederive only the two reviewed slow-path overlays."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import shutil

HERE = Path(__file__).resolve().parent
MANIFEST = 'CANDIDATE.sha256'
loop = runpy.run_path(str(HERE/'derive-mega-loop-repair.py'))
miss = runpy.run_path(str(HERE/'derive-mega-miss-select.py'))
seals = runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']


def digest(data):
    return sha256(data).hexdigest()


def require(check, message):
    if not check:
        raise ValueError(message)


def build(stock, dest, sat_file, queue_file, include_miss, clocked_file=None):
    stock = stock.resolve(strict=True)
    dest = dest.resolve()
    require(not dest.exists() and stock not in dest.parents and dest not in stock.parents, 'need fresh unrelated output')
    base = seals(stock)
    base_id = digest((stock/MANIFEST).read_bytes())
    require(base_id == loop['KIT'] == miss['KIT'], 'wrong stock input')
    seq = (stock/'sources.f').read_text().splitlines()
    require(len(seq) == len(set(seq)) == 549 and set(seq) == {k for k in base if k.startswith('rtl/')}, 'wrong ordered source set')
    fb = json.loads((HERE.parent/'docs/perf-mega175-loop-repair.json').read_bytes())
    ooc = json.loads((HERE.parent/'docs/perf-mega175-loop-ooc.json').read_bytes())
    blocks = loop['derive'](loop['sealed'](stock))
    front = {n:digest(v.encode()) for n,v in blocks.items()}
    require(front == fb['candidate_sha256'] == ooc['cases']['candidate']['rtl_sha256'] and fb['formal']['candidate']['decision']=='equivalent_step' and fb['lockstep']['ignore_bit35']=='output_mismatch', 'unchecked front end')
    if include_miss:
        sat = json.loads(sat_file.read_bytes()); queue = json.loads(queue_file.read_bytes())
        text = miss['derive'](miss['sealed'](stock)); ident = digest(text.encode())
        require(ident == sat['candidate_unit_sha256'] == queue['candidate_sha256'] and sat['stock_sha256']==miss['HASH'] and sat['board_kit_sha256']==base_id, 'unmatched queue receipts')
        require(sat['sat']=={'candidate':'equivalent','cross_slot9':'counterexample','omit_p2_poison':'counterexample'} and (sat['move_valid_outputs'],sat['resident_valid_outputs'])==(40,40), 'missing proof')
        require(queue['results']=={'candidate':'matched','cross_slot9':'mismatch detected, destination 8 from slot 9'} and (queue['resident_pairs'],queue['rescue_high_low_sequences'],queue['dispatch_pairs'])==(150,300,10), 'missing queue test')
        require(clocked_file is not None, 'missing unforced clocked queue test')
        clocked = json.loads(clocked_file.read_bytes())
        require(clocked['candidate_sha256']==ident and clocked['issue_valid_lane_samples']>=200 and 0<clocked['slot8_sensitive_samples']<=clocked['miss_sensitive_move_samples'] and 0<=clocked['cross_slot9_rejected_cycle']<1200, 'unmatched clocked test or negative control')
        blocks[miss['UNIT']] = text
    leaves = {'rtl/'+n+'.sv':v.encode() for n,v in blocks.items()}
    require(set(leaves)<=set(seq), 'non-HDL change')
    shutil.copytree(stock,dest)
    for name, raw in leaves.items():
        (dest/name).write_bytes(raw)
    actual = {k:digest((dest/k).read_bytes()) for k in base}
    require({k for k in base if actual[k]!=base[k]}==set(leaves),'unexpected delta')
    (dest/MANIFEST).write_bytes(''.join(f'{v}  {k}\n' for k,v in sorted(actual.items())).encode())
    require(seals(dest)==actual and seals(stock)==base and digest((stock/MANIFEST).read_bytes())==base_id,'failed final seal')
    return dict(scope='New physical source input only. No timing, functional Linux, or board qualification for this combination. Historical model receipts embedded in the base kit describe the base, not this candidate.',stock_sha256=base_id,candidate_sha256=digest((dest/MANIFEST).read_bytes()),sealed_members=len(actual),ordered_hdl=len(seq),ordered_list_sha256=actual['sources.f'],changed={k:actual[k] for k in sorted(leaves)},clock_request_mhz=175)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('stock','dest','sat','queue'): p.add_argument(key,type=Path)
    p.add_argument('--clocked',type=Path);p.add_argument('--with-miss',action='store_true');a=p.parse_args()
    print(json.dumps(build(a.stock,a.dest,a.sat,a.queue,a.with_miss,a.clocked),indent=2))
