#!/usr/bin/env python3
"""Compare two complete top-level synth cell tables, without opening Vivado or reading an active placer database."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

TOP = 'VCU118FPGATestHarness'
PART = 'xcvu9p-flga2104-2L-e'
SEALS = ('6c9528b1f3c8d18584b3b095d7d20399fc7b5cb56668a9d656af31cc7df93147',
         'b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959')
KEYS = tuple('LUT'+str(i) for i in range(1,7)) + ('FDRE','RAMB18E2','RAMB36E2','MUXF7','MUXF8')


def digest(path):
    h = sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def portable(path):
    s = str(path).replace('\\','/')
    m = re.fullmatch(r'/mnt/([a-zA-Z])/(.*)',s)
    return ((m[1]+':/'+m[2]) if m else s).casefold()


def cell_table(text):
    pat = (r'^Report Cell Usage: *\n(?P<table>\+[-+]+\n\| +\|Cell +\|Count *\|\n\+[-+]+\n'
           r'(?:\|[0-9 ]+\|[A-Z0-9_]+ *\| *\d+ *\|\n)+\+[-+]+)$')
    got = re.findall(pat,text,re.M)
    if len(got) != 1 or text.count('Report Cell Usage:') != 1: raise ValueError('missing, ambiguous or partial cell table')
    matches = re.findall(r'^\| *(\d+) *\|([A-Z0-9_]+) *\| *(\d+) *\|$',got[0],re.M)
    ids = [int(i) for i,_,_ in matches]; counts = {k:int(n) for _,k,n in matches}
    if ids != sorted(set(ids)) or len(counts)!=len(matches) or not set(KEYS)<=counts.keys(): raise ValueError('missing or repeated primitive')
    return counts,sha256(got[0].encode()).hexdigest()


def review(log,kit,dcp,seal):
    for p in (log,kit,dcp): p.resolve(strict=True)
    if digest(kit/'CANDIDATE.sha256')!=seal: raise ValueError('incorrect implementation seal')
    recorded = {}
    for line in (kit/'CANDIDATE.sha256').read_text().splitlines():
        h,name=line.split('  ',1); member=(kit/name).resolve(strict=True)
        if kit.resolve() not in member.parents or name in recorded or digest(member)!=h: raise ValueError('changed implementation input')
        recorded[name]=h
    run=dcp.resolve().parents[1]; sources=(kit/'sources.f').read_text().splitlines()
    if (dcp.name!='post_synth.dcp' or not all(k in recorded for k in ['implement.tcl','sources.f',*sources])
            or [portable(kit.resolve()/k) for k in sources] != [portable(s) for s in (run/'sources.windows.f').read_text().splitlines()]):
        raise ValueError('different synthesized source list or stage')
    prefix=log.read_text(errors='replace').split('\nVCU118_STAGE=opt\n',1)
    if len(prefix)!=2: raise ValueError('incomplete synthesis')
    header,stage=prefix[0].split('\nVCU118_STAGE=synth\n'); command,=re.findall(r'^# Command line +: (.*)$',header,re.M)
    args=command.split(' -tclargs ',1)[1]; expected=[kit.resolve()/'implement.tcl',kit.resolve()/'sources.f',kit.resolve()/'shell/xilinx/common/tcl',run]
    if portable(args) != ' '.join(portable(p) for p in expected) or '# Vivado v2024.2 (64-bit)' not in header:
        raise ValueError('wrong implementation inputs, run directory or tool')
    stage=stage.split('Command: synth_design -top '+TOP+' -flatten_hierarchy rebuilt\n')[1]
    success="synth_design completed successfully"; body,tail=stage.split('\n'+success+'\n'); cp,=re.findall(r"^INFO: \[Common 17-1381\] The checkpoint '([^']+/post_synth.dcp)' has been generated\.$",tail,re.M)
    if portable(cp)!=portable(dcp.resolve()) or not re.search(r'^Synthesis finished with 0 errors, 0 critical warnings and \d+ warnings\.$',body,re.M):
        raise ValueError('unconfirmed top-level synthesis/checkpoint')
    with ZipFile(dcp) as z: xml=ET.fromstring(z.read('dcp.xml'))
    for tag,value in (('PRODUCT','Vivado v2024.2 (64-bit)'),('Top',TOP),('Part',PART),('OutOfContext','0')):
        if [x.get('Name') for x in xml.findall(tag)] != [value]: raise ValueError('checkpoint metadata: '+tag)
    counts,table_hash=cell_table(body)
    return dict(board_input_seal=seal,post_synth_dcp_sha256=digest(dcp),cell_table_sha256=table_hash,
                primitives={k:counts[k] for k in KEYS},sum_LUT1_to_LUT6=sum(counts['LUT'+str(i)] for i in range(1,7)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('three_log','three_kit','three_dcp','four_log','four_kit','four_dcp'): p.add_argument(name,type=Path)
    a=p.parse_args(); x,y=[review(*(getattr(a,label+'_'+q) for q in ('log','kit','dcp')),seal) for label,seal in zip(('three','four'),SEALS)]
    print(json.dumps(dict(scope='Whole-SoC synthesis table, 175 MHz requested. Different BOOM organizations and debug/RX revisions. Raw primitive instances, not occupied CLB LUT sites, post-route utilization, timing, or a CPU-only area measurement.',
                          three_wide_stock=x,four_wide_split=y,LUT1_to_LUT6_delta_percent=round(100*(y['sum_LUT1_to_LUT6']/x['sum_LUT1_to_LUT6']-1),4)),indent=2))
