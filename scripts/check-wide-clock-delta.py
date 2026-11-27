#!/usr/bin/env python3
"""Compare two complete sealed HDL manifests for the 100/175 MHz BOOM clock change."""
from hashlib import sha256
import json
from pathlib import Path
import argparse


def check(old,new,family='Large'):
    if family not in ('Large','Mega'):
        raise ValueError('unknown BOOM family')
    def read(kit):
        paths=(kit/'sources.f').read_text().splitlines(); data={}
        manifest={}
        for row in (kit/'CANDIDATE.sha256').read_text().splitlines():
            digest,name=row.split('  ',1)
            if name in manifest:raise ValueError('duplicate sealed file')
            manifest[name]=digest
        if len(paths)<300 or len(paths)!=len(set(paths)):raise ValueError('unexpected HDL list')
        for name in ['sources.f',*paths]:
            p=(kit/name).resolve(strict=True)
            if kit.resolve() not in p.parents:raise ValueError('path outside kit')
            digest=sha256(p.read_bytes()).hexdigest()
            if digest!=manifest.get(name):raise ValueError('sealed input changed')
            data[name]=digest
        return data
    a,b=read(old),read(new)
    # The generated memory wrapper filenames include the config class. Their
    # contents, and the BOOM core hierarchy, must remain byte-identical.
    def name(p):return p.replace('Perf'+family+'BoomVCU118Config.', 'Perf175'+family+'BoomVCU118Config.').replace('AsyncResetRegVec_w14_i0.sv','AsyncResetRegVec_w15_i0.sv')
    names=[p for p in a if p!='sources.f']
    wrapper = 'rtl/chipyard.fpga.vcu118.VCU118FPGATestHarness.Perf'+family+'BoomVCU118Config.'
    if not {wrapper+'top.mems.v', wrapper+'model.mems.v'} <= set(names):
        raise ValueError('control is not the selected BOOM family')
    if len({name(p) for p in names})!=len(names) or set(map(name,names))!=set(b)-{'sources.f'}:raise ValueError('unmatched HDL files')
    if [name(p) for p in names] != [p for p in b if p!='sources.f']:
        raise ValueError('HDL source order differs')
    changes={p:[a[p],b[name(p)]] for p in names if a[p]!=b[name(p)]}
    translations={
        'rtl/TLUART.sv': [(b"div <= 16'h364;",b"div <= 16'h5EF;")],
        'rtl/ResetWrangler.sv':[(b'[13:0] _debounced',b'[14:0] _debounced'),(b"14'h2710",b"15'h445C"),(b'AsyncResetRegVec_w14_i0',b'AsyncResetRegVec_w15_i0'),(b"+ 14'h1",b"+ 15'h1")],
        'rtl/AsyncResetRegVec_w14_i0.sv':[(b'w14_i0',b'w15_i0'),(b'[13:0]',b'[14:0]'),(b"14'h0",b"15'h0")],
    }
    if set(changes)!=set(translations)|{'rtl/TLROM.sv'}:raise ValueError('unexpected differing HDL files: '+str(list(changes)))
    for key,replacements in translations.items():
        data=(old/key).read_bytes()
        for x,y in replacements:
            if x not in data:raise ValueError('unexpected reference expression: '+key)
            data=data.replace(x,y)
        if data!=(new/name(key)).read_bytes():raise ValueError('unaccounted changes: '+key)
    return dict(scope='Sealed HDL inputs, including the board harness. PLL constraints, generated ROM/DT semantics, routed frequency, and board performance require separate checks.',hdl_files=len(names),byte_identical_hdl_files=len(names)-len(changes),ordered_list_preserved_after_renaming=[name(p) for p in names]==[p for p in b if p!='sources.f'],changes=changes,renamed={p:name(p) for p in names if name(p)!=p},inputs=[sha256((p/'CANDIDATE.sha256').read_bytes()).hexdigest() for p in (old,new)])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('control',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--family',choices=('Large','Mega'),default='Large');a=p.parse_args();print(json.dumps(check(a.control,a.candidate,a.family),indent=2))
