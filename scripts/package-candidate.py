#!/usr/bin/env python3
"""Archive exactly the ROM4 kit passed to Vivado; reject unlisted/missing/changed inputs."""
import argparse, hashlib, zipfile, os, tempfile
from pathlib import Path, PurePosixPath

def need(value, why):
    if not value: raise ValueError(why)

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('kit',type=Path); ap.add_argument('out',type=Path); args=ap.parse_args()
    manifest='CANDIDATE.sha256'; kit=args.kit.resolve(); out=args.out.resolve(); need(not out.exists(),'fresh archive path required')
    rows=(kit/manifest).read_text().splitlines(); files={}
    for row in rows:
        digest,name=row.split('  ',1); p=PurePosixPath(name)
        need(not p.is_absolute() and not any(s in name for s in ('\\',':')) and '..' not in p.parts and name not in files and name==p.as_posix(),name)
        path=(kit/name).resolve(); need(kit in path.parents and path.is_file(),name); b=path.read_bytes(); need(hashlib.sha256(b).hexdigest()==digest,'hash mismatch: '+name); files[name]=b
    files[manifest]=(kit/manifest).read_bytes(); need(set(files)=={x.relative_to(kit).as_posix() for x in kit.rglob('*') if x.is_file()},'kit has unlisted files; use pristine inputs, not a run directory')
    names=files['sources.f'].decode().splitlines(); need(len(names)==len(set(names)) and len(names)>300 and all(n in files for n in names),'manifest path mismatch')
    fd,tmp=tempfile.mkstemp(dir=out.parent,suffix='.part');os.close(fd)
    try:
        with zipfile.ZipFile(tmp,'w') as z:
            for name,b in sorted(files.items()):
                i=zipfile.ZipInfo(name,(2024,12,1,0,0,0)); i.compress_type=zipfile.ZIP_STORED; i.create_system=3; i.external_attr=0o100644<<16; z.writestr(i,b)
        with zipfile.ZipFile(tmp) as z:
            need(z.testzip() is None and all(z.read(n)==b for n,b in files.items()),'read-back differed')
        # Do not overwrite a previously delivered archive even if a concurrent process won.
        os.link(tmp,out)
        print('CANDIDATE_ZIP_VERIFIED sources=%d files=%d sha256=%s'%(len(names),len(files),hashlib.sha256(out.read_bytes()).hexdigest()))
    finally: os.unlink(tmp)
if __name__=='__main__': main()
