#!/usr/bin/env python3
"""Verify that the one-switch Linux experiment changed executable code, not just the flag string."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

CONTROL='0ab2e1c3baf03a98c23383268e1f792c9d955e6fe54b15c0e536ac21f22a4232'
TUNED='54144e7c53a35078afe3f075469e68e87ea9b5de6837530f4be76c67725ecce9'

PROFILES = (
    ('g15-gc-lto', CONTROL, (), True),
    ('g15-gc-lto-ooo', TUNED, ('-mtune=generic-ooo',), False),
    ('g15-gc-lto-ooo-strict', '61f7c4579b762f86d7d7dc93d4c385d08e50248f3dd6a8a9105fd5e88b58886a', ('-mtune=generic-ooo','-mstrict-align'), True),
    ('g15-gc-lto-relaxed', '35419f1ea8ece2ceed2c0831d00c562752d52c1602e97d94e35667e1ac81112c', ('-mno-strict-align',), False),
)


def inspect(release, factorial=False):
    tools=Path(os.getenv('VCU_TOOLS',Path.home()/'.local/share/vcu118-tools'))
    prefix=str(tools/'bootlin-cpu-2025.08-1/bin/riscv64-linux-')
    def read(tool,*args):return subprocess.check_output([prefix+tool,*args],text=True,env={**os.environ,'LC_ALL':'C'})
    if read('gcc','-dumpfullversion').strip()!='15.1.0':raise ValueError('wrong GCC')
    rows=[]
    with tempfile.TemporaryDirectory() as td:
        for i,(suffix,identity,extra,strict_wanted) in enumerate(PROFILES if factorial else PROFILES[:2]):
            elf=release/('coremark-'+suffix+'.elf')
            if sha256(elf.read_bytes()).hexdigest()!=identity:raise ValueError('unexpected ELF identity: '+suffix)
            attrs=read('readelf','-A',elf); arch,=re.findall(r'^  Tag_RISCV_arch: "([^"\n]+)"$',attrs,re.M)
            if re.search(r'_(zba|zbb)\d',arch) or not arch.startswith('rv64i') or '  Tag_RISCV_stack_align: 16-bytes' not in attrs:raise ValueError('unexpected RV64GC attributes')
            access=re.findall(r'^  Tag_RISCV_unaligned_access: (.*)$',attrs,re.M)
            if access!=([] if strict_wanted else ['Unaligned access']):raise ValueError('unexpected ELF unaligned-access attribute')
            if 'INTERP' in read('readelf','-lW',elf):raise ValueError('expected a static Linux executable')
            opts=read('gcc','-Q','-O3','-flto','-march=rv64gc','-mabi=lp64d',*extra,'--help=target')
            abi,=re.findall(r'^\s*-mabi=[ \t]+(\S+)[ \t]*$',opts,re.M)
            march,=re.findall(r'^\s*-march=[ \t]+(\S+)[ \t]*$',opts,re.M)
            tune,=re.findall(r'^\s*-mtune=PROCESSOR[ \t]*([^\s]*)[ \t]*$',opts,re.M)
            strict,=re.findall(r'^\s*-mstrict-align[ \t]+\[(enabled|disabled)\][ \t]*$',opts,re.M)
            if strict!=('enabled' if strict_wanted else 'disabled'):raise ValueError('unexpected effective alignment policy')
            if abi!='lp64d' or (tune or None)!=('generic-ooo' if '-mtune=generic-ooo' in extra else None):raise ValueError('unexpected compiler options')
            text=Path(td)/str(i);subprocess.run([prefix+'objcopy','-O','binary','--only-section=.text',elf,text],check=True)
            data=text.read_bytes()
            if len(data)<4096:raise ValueError('empty/truncated text section')
            rows.append(dict(profile=suffix,elf_sha256=identity,text_bytes=len(data),text_sha256=sha256(data).hexdigest(),elf_arch=arch,effective_march=march,abi=abi,explicit_mtune=tune or None,effective_strict_align=(strict=='enabled'),elf_declares_unaligned_access=bool(access)))
    if factorial:
        if (len({(r['explicit_mtune'],r['effective_strict_align']) for r in rows})!=4 or
                len({r['text_sha256'] for r in rows})!=4 or
                len({(r['abi'],r['effective_march'],r['elf_arch']) for r in rows})!=1):
            raise ValueError('not a full two-factor code comparison with fixed ISA and ABI')
        return dict(scope='Four pinned static Linux ELFs, common GCC, ISA and ABI. The factors are requested tuning and effective alignment policy, not guaranteed distinct hardware mechanisms. No benchmark result.',compiler='GCC 15.1.0',profiles=rows)
    a,b=rows
    if any(a[k]!=b[k] for k in ('elf_arch','effective_march','abi')) or a['text_sha256']==b['text_sha256']:raise ValueError('ISA changed or machine code identical')
    return dict(scope='Static comparison of the two pinned Linux executables. The single explicit tuning switch also changes the implicit alignment policy. Section sizes and fingerprints do not measure throughput.',compiler='GCC 15.1.0',reference=a,candidate=b,text_size_delta_bytes=b['text_bytes']-a['text_bytes'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('release',type=Path);p.add_argument('--factorial',action='store_true');a=p.parse_args();print(json.dumps(inspect(a.release,a.factorial),indent=2))
