#!/usr/bin/env python3
"""Derive fixed-length CRC oracles from unmodified POSIX CoreMark; no host score."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
CM=runpy.run_path(str(ROOT/'scripts/review-coremark.py'))

SHORT = 'ERROR! Must execute for at least 10 secs for a valid result!'
VALID = 'Correct operation validated. See README.md for run and reporting rules.'


def field(lines, key):
    hits = [m[1].strip() for line in lines
            if (m := re.fullmatch(re.escape(key) + r'\s*:\s*(.+)', line))]
    if len(hits) != 1:
        raise ValueError('missing or duplicate field: ' + key)
    return hits[0]


def crc(text, kind, n):
    lines = text.splitlines()
    final = field(lines, '[0]crcfinal')
    if (lines.count(f'2K {kind} run parameters for coremark.') != 1
        or field(lines, 'Iterations') != str(n) or field(lines, 'CoreMark Size') != '666'
        or tuple(field(lines, k) for k in ('seedcrc','[0]crclist','[0]crcmatrix','[0]crcstate')) != CM['CASES'][kind][1:]
        or not re.fullmatch(r'0x[0-9a-f]{4}', final)
        or any(s.startswith('Parallel ') or re.match(r'\[(?!0\])\d+\]crc', s) for s in lines)):
        raise ValueError('wrong run, seed, context, data size or kernel CRCs')
    # Upstream emits this single duration error on a fast host. Accept its CRC
    # only, not its throughput. Other diagnostics, even beside this one, fail.
    errors = [s for s in lines if 'ERROR!' in s or 'Cannot validate operation' in s or 'Kernel panic' in s]
    if (errors not in ([], [SHORT]) or lines.count('Errors detected') != int(bool(errors))
        or lines.count(VALID) != int(not errors)):
        raise ValueError('non-timing failure in CRC oracle')
    return final


def guest_crcs(raw, nonce, elf_hash, profile, n):
    text = raw.decode('ascii').replace('\r', '')
    if 'Kernel panic' in text or 'Cannot validate operation' in text:
        raise ValueError('invalid guest boot or workload')
    lines = text.splitlines()

    def marker(s):
        hits = [j for j, line in enumerate(lines) if line in (s, '# ' + s)]
        if len(hits) != 1:
            raise ValueError('missing or duplicate marker: ' + s)
        return hits[0]

    isa_cmd = marker('cat /proc/cpuinfo; echo ISA_END_$((40+2))_' + nonce)
    isa_end = marker('ISA_END_42_' + nonce)
    cpu = lines[isa_cmd+1:isa_end]
    isa = field(cpu, 'isa')
    if field(cpu,'processor') != '0' or field(cpu,'hart') != '0' or not isa.startswith('rv64imafdc') or {'zba','zbb'} & set(isa.split('_')):
        raise ValueError('wrong guest CPU')
    last = marker(elf_hash + '  ' + CM['binary'](profile))
    if not isa_cmd < isa_end < marker('CM_LIVE_42_' + nonce) < marker(CM['command'](nonce,n,profile)) < last:
        raise ValueError('guest command not observed in this epoch')
    result = {}
    for kind in CM['CASES']:
        start, end = marker('CM_' + kind + '_42_' + nonce), marker('CM_' + kind + '_RC_0_' + nonce)
        if not last < start < end:
            raise ValueError('wrong guest order')
        section = lines[start+1:end]
        if field(section,'Compiler version') != CM['expected_compiler'](profile) or ' '.join(field(section,'Compiler flags').split()) != CM['PROFILES'][profile][1]:
            raise ValueError('wrong guest compiler or flags')
        result[kind] = crc('\n'.join(section), kind, n)
        last = end
    if marker('CM_DONE_42_' + nonce) <= last:
        raise ValueError('unfinished guest CRC run')
    return result


def check_guest(raw, nonce, elf, fw):
    profile = 'g15-gc-lto-ooo-strict'; n = 24000
    digest = lambda p: sha256(p.read_bytes()).hexdigest()
    e, f = digest(elf), digest(fw)
    codes = json.loads((ROOT/'docs/linux-align-code.json').read_bytes())['profiles']
    if (not re.fullmatch(r'[a-f0-9]{14}',nonce) or [v['elf_sha256'] for v in codes if v['profile']==profile] != [e]
        or f != json.loads((ROOT/'docs/linux-align-rocket-boot.json').read_bytes())['packed_stage']['raw_sha256']):
        raise ValueError('unmatched guest inputs')
    guest = guest_crcs(raw,nonce,e,profile,n)
    expected = json.loads((ROOT/'docs/coremark-target-length-crcs.json').read_bytes())['final_crc_by_iterations'][str(n)]
    if guest != expected:
        raise ValueError('guest disagrees with independently derived native CRCs')
    return dict(profile=profile,iterations=n,elf_sha256=e,firmware_sha256=f,crc_only=True,final_crcs=guest,uart_sha256=sha256(raw).hexdigest())


def build(archive):
    name=f"coremark-{CM['REV']}.tar.gz";d=sha256(archive.read_bytes()).hexdigest()
    if f'{d}  {name}' not in (ROOT/'sources.sha256').read_text().splitlines():raise ValueError('not the pinned CoreMark archive')
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp);s=t/('coremark-'+CM['REV']);
        # Only after checking the fixed archive digest against the repository lock.
        with tarfile.open(archive,'r:gz') as f:f.extractall(t)
        subprocess.run(['make','-s','-C',s,'PORT_DIR=posix','check'],stdout=subprocess.PIPE,check=True)
        comp=subprocess.check_output(['gcc','-dumpfullversion'],text=True).strip();modes={}
        for flag in ('-O0','-O2'):
            out=t/flag[1:];out.mkdir();exe=out/'coremark.exe';subprocess.run(['make','-s','-C',s,'PORT_DIR=posix','CC=gcc','ITERATIONS=0','OPATH='+str(out)+'/', 'PORT_CFLAGS='+flag, str(exe)],check=True,stdout=subprocess.PIPE)
            rows={}
            for n in (12000,24000):
                row={}
                for k,(seed,*_) in CM['CASES'].items():
                    output=subprocess.check_output([exe,seed,seed,'0x66',str(n),'7','1','2000'],text=True)
                    row[k]=crc(output,k,n)
                rows[str(n)]=row
            modes[flag]=rows
        if modes['-O0']!=modes['-O2'] or modes['-O2']['12000']!={'performance':'0xd340','validation':'0xbc68'}:raise ValueError('cross-build CRC mismatch')
    return dict(scope='Native x86 POSIX CRC oracle only, not a benchmark result or hardware evidence.',archive_sha256=d,upstream=CM['REV'],compiler='GCC '+comp,compared_optimization_flags=list(modes),contexts=1,total_buffer_bytes=2000,final_crc_by_iterations=modes['-O2'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);print(json.dumps(build(p.parse_args().archive),indent=2))
