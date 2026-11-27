#!/usr/bin/env python3
"""Re-prove and seal separate four-wide inputs; never run Vivado or access a board."""
import argparse
from pathlib import Path
import json
import runpy
import shutil

HERE=Path(__file__).resolve().parent
G=runpy.run_path(str(HERE/'prove-mega-issue-grants.py')); M=G['M']
seals=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']
LEAF='rtl/'+M['NAME']; MANIFEST='CANDIDATE.sha256'


def delta(old,new):
    if old.keys()!=new.keys() or {n for n in old if old[n]!=new[n]}!={LEAF} or old[LEAF]!=M['UNIT']:
        raise ValueError('only the stock integer issue unit may change')


def require_results(result,cases):
    if {n:v['result'] for n,v in result.items()}!=cases:raise ValueError('missing, extra, or inconclusive proof')


def derive(kit,out,yosys):
    kit=kit.resolve(strict=True);out=out.resolve();digest=M['digest']
    if out.exists() or kit in out.parents or out in kit.parents:raise ValueError('need fresh output outside input tree')
    if digest((kit/MANIFEST).read_bytes())!=M['KIT']:raise ValueError('wrong original physical kit')
    old=seals(kit);ordered=(kit/'sources.f').read_text().splitlines()
    if len(ordered)!=len(set(ordered)) or len(ordered)!=549 or ordered.count(LEAF)!=1:raise ValueError('wrong ordered HDL input')
    out.mkdir();mux=M['run'](kit,out/'mux',yosys);grant=G['run'](kit,out/'grants',yosys)
    mux_cases={**{f'onehot-port-{p}':'proved' for p in range(4)},**{f'payload-idle-{b}':'proved' for b in (0,1)},'grant-negative':'counterexample','payload-negative':'counterexample'}
    grant_cases={**{f'group8-port{p}':'proved' for p in range(4)},'omit_slot0-port0':'counterexample'}
    require_results(mux['proofs'],mux_cases);require_results(grant['port_equivalence_under_previously_proved_ports'],grant_cases)
    # Recompose the proven pieces from the saved single-edit variants. Refuse
    # to copy an artifact if it differs from either order of composition.
    src=(kit/LEAF).read_bytes().decode(); gs=M['grants'](src)
    first=(out/'mux'/M['NAME']).read_bytes();second=(out/'grants/grant-only.sv').read_bytes();both=(out/'grants/grant-and-mux.sv').read_bytes()
    if (digest(first)!=mux['variant_sv_sha256'] or digest(second)!=grant['grant_only_sv_sha256'] or
        digest(both)!=grant['grant_and_mux_sv_sha256'] or M['derive'](second.decode())[0].encode()!=both or
        G['replace_cone'](first.decode(),gs,G['parallel_select'](gs)).encode()!=both):raise ValueError('proof variants do not match candidate bytes')
    candidates={}
    for label,raw in [('grouped_grants',second),('both',both)]:
        dst=out/label;shutil.copytree(kit,dst);(dst/LEAF).write_bytes(raw)
        new={n:digest((dst/n).read_bytes()) for n in old};delta(old,new)
        (dst/MANIFEST).write_bytes(''.join(f'{h}  {n}\n' for n,h in sorted(new.items())).encode())
        if seals(dst)!=new:raise ValueError('unexpected member in derived source')
        candidates[label]=dict(board_input_seal=digest((dst/MANIFEST).read_bytes()),changed={LEAF:new[LEAF]})
    if seals(kit)!=old or digest((kit/MANIFEST).read_bytes())!=M['KIT']:raise ValueError('source changed during derivation')
    return dict(scope='Two one-leaf experimental board source inputs, separate from stock. Two-state combinational checks, no coupled CPU simulation, no implementation, no physical timing or board result. Inherited model receipts describe the stock input only.',
                stock_board_input_seal=M['KIT'],candidates=candidates,ordered_hdl_files=len(ordered),sealed_members=len(old),
                stock_sv_sha256=old[LEAF],unchanged_ordered_sources_sha256=old['sources.f'],solver=mux['solver'],
                mux_proof=mux,grant_proof=grant)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('kit',type=Path);ap.add_argument('out',type=Path);ap.add_argument('--yosys',default='yosys');a=ap.parse_args()
    result=derive(a.kit,a.out,a.yosys);(a.out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('TWO_SEPARATE_ISSUE_INPUTS_NO_PHYSICAL_RESULT')
