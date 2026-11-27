#!/usr/bin/env python3
"""Build an isolated full-SoC MSHR command-class candidate from the recovery kit."""
import argparse
import json
from pathlib import Path
import runpy
import shutil

HERE=Path(__file__).resolve().parent
C=runpy.run_path(str(HERE/'test-mega-mshr-connected.py')); M=C['M']; D=C['D']
seals=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']
need=C['need']; h=C['h']; lock='CANDIDATE.sha256'


def record(n):return json.loads((HERE.parent/'docs'/n).read_bytes())


def prepare(base,dest):
    base=base.resolve(strict=True); need(not dest.is_symlink(), 'symlink destination');dest=dest.resolve();need(not dest.exists() and base not in dest.parents and dest not in base.parents,'fresh disjoint kit required')
    ready=record('perf-mega175-mshr-ready.json'); connected=record('perf-mega175-mshr-connected.json'); qualified=seals(base); parent_hash=h((base/lock).read_bytes())
    need(ready['physical_sha256']==connected['physical_sha256']==parent_hash,'wrong physical base')
    seq=(base/'sources.f').read_text().splitlines();need(len(seq)==len(set(seq))==549 and set(seq)=={k for k in qualified if k.startswith('rtl/')},'changed source ordering or membership')
    full=M['load'](base); src,_=D['kit_sources'](base);D['verify_links'](src)
    p,c,q=(full[M[n]] for n in ('P','C','Q'));newp,newc=M['derive'](p,c,True)
    for case,a,b in [('stock',p,c),('class_local',newp,newc)]:
        ref=ready['sha256'][case]; need(h(a.encode())==ref['parent'] and h(b.encode())==ref['child'] and h(M['extract'](a,b)[0].encode())==ref['cut'],'ready cut or production text changed')
        cut,_=C['connected'](case,a,b,q,src);need(h(cut.encode())==connected['cuts_sha256'][case],'downstream consumer cut changed')
    need(ready['proofs']['class_local']=='equivalent' and connected['proofs']['class_local']=={'status':'equivalent'}, 'missing same-cycle checks')
    leaves={'rtl/'+name+'.sv':text.encode() for name,text in [(M['P'],newp),(M['C'],newc)]};need(set(leaves)<=set(seq),'wrong files')
    shutil.copytree(base,dest)
    for k,raw in leaves.items():(dest/k).write_bytes(raw)
    sums={k:h((dest/k).read_bytes()) for k in qualified};changes={k:sums[k] for k in sums if sums[k]!=qualified[k]};need(set(changes)==set(leaves),'unexpected changes')
    (dest/lock).write_bytes(''.join(f'{v}  {k}\n' for k,v in sorted(sums.items())).encode('ascii'))
    need(seals(dest)==sums and seals(base)==qualified and h((base/lock).read_bytes())==parent_hash,'kit sealing failed')
    return dict(scope='Sealed physical inputs only; a separate test candidate, not a synthesized design, OOC timing transfer, or board score.',base_sha256=parent_hash,candidate_sha256=h((dest/lock).read_bytes()),ordered_hdl=len(seq),ordered_list_sha256=sums['sources.f'],sealed_members=len(sums),changed=changes,connected_cut_sha256=connected['cuts_sha256']['class_local'])


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('base',type=Path);ap.add_argument('dest',type=Path);a=ap.parse_args();print(json.dumps(prepare(a.base,a.dest),indent=2))
