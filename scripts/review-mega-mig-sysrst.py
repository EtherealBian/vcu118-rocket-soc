#!/usr/bin/env python3
"""Audit MIG input-reset exception serialization (not a constraint waiver).

Ordinarily point at one completed checkpoint. The optional archived-route mode
also checks the original, pinned pre-physopt DCP and its actual timing report.
Read only the small XDC/XML members; never execute checkpoint Tcl or open a design.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

TOP='VCU118FPGATestHarness'
SCOPE='mig/island/blackbox/inst'
TARGET='u_ddr4_infrastructure/sys_rst'
CMD='set_false_path -through [get_pins '+TARGET+']'
PART='xcvu9p-flga2104-2L-e'
OLD_DCP='d0ead1ae8498f90d6ec268dc12c7f26d745448bcf2c20b4ce681a4dd356ef581'
OLD_TIMING='120b9ea1c595fabe7db8aaa657f000c036a3dfbd92b86ee9342f9868b4096d8a'


def need(ok,why):
    if not ok: raise ValueError(why)


def file_id(path):
    h=sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def inspect(dcp):
    dcp=dcp.resolve(strict=True); xdc=dcp.parent/'ip/vcu118mig/par/vcu118mig.xdc'
    need(xdc.read_text().splitlines()[294].strip()==CMD,'different generated IP exception')
    with ZipFile(dcp) as z:
        root=ET.fromstring(z.read('dcp.xml'))
        for key,value in [('BUILD_NUMBER','5239630'),('Part',PART),('Top',TOP),('OutOfContext','0')]:
            need([v.get('Name') for v in root.findall(key)]==[value],'wrong checkpoint: '+key)
        early=[e.get('Name') for e in root.findall('File') if e.get('Type')=='XDC_EARLY']
        need(early==[TOP+'_early.xdc'],'unexpected XDC file'); raw=z.read(early[0]); lines=raw.decode().splitlines()
    hits=[i for i,v in enumerate(lines) if v==CMD]; need(len(hits)==1 and hits[0]>0,'missing or duplicated exception'); i=hits[0]
    scope=[v for v in lines[:i] if v.startswith('current_instance ')]; need(scope and scope[-1]=='current_instance '+SCOPE,'wrong scope')
    meta=re.fullmatch(r'set_property src_info \{type:SCOPED_XDC file:(\d+) line:295 export:INPUT save:INPUT read:READ\} \[current_design\]',lines[i-1]); need(meta,'wrong source line')
    refs=[v for v in lines if v.startswith('set_property SRC_FILE_INFO ') and ' id:'+meta[1]+' ' in v]; need(len(refs)==1,'unclear input attribution')
    src=refs[0]; need(' rfile:ip/vcu118mig/par/vcu118mig.xdc ' in src and ' scoped_inst:'+SCOPE+' ' in src,'wrong scoped IP input')
    # Disallow pairing a copied current-run DCP with an identical old IP generated under another build root.
    original=re.search(r'\{cfile:(.*?) rfile:',src); need(original and Path(original[1]).resolve()==xdc.resolve(),'checkpoint names another build directory')
    return dict(checkpoint_sha256=file_id(dcp),stage_filename=dcp.name,early_xdc_sha256=sha256(raw).hexdigest(),generated_xdc_sha256=file_id(xdc),scope=SCOPE,source_line=295,serialized=True)


def old_paths(dcp_id,rpt):
    need(dcp_id==OLD_DCP and file_id(rpt)==OLD_TIMING,'not the archived old report/checkpoint pair'); text=rpt.read_text()
    need('| Design State      : Routed' in text and '| Design            : '+TOP in text,'not routed four-wide report')
    end=SCOPE+'/u_ddr4_infrastructure/rst_input_async_reg[0]/PRE'; path=SCOPE+'/'+TARGET
    rows={}; blocks=re.split(r'(?m)(?=^Slack(?:\s*\(|:))',text)
    for b in blocks:
        if not re.search(r'(?m)^  Destination:\s+'+re.escape(end)+r'\s*$',b): continue
        def field(n):
            vs=re.findall(r'(?m)^  '+n+r':\s+([^\r\n]+)',b); need(len(vs)==1,'missing field: '+n); return vs[0].strip()
        source=field('Source'); kind=field('Path Type'); k=(source,kind.split()[0]); need(k not in rows,'duplicate timing arc')
        need(b.splitlines()[0].split()==['Slack:','inf'] and field('Timing Exception')=='False Path' and any(l.split()[-1:]==[path] and 'net (fo=3, routed)' in l for l in b.splitlines()),'different reset status')
        need('rising-edge clock sys_clock' in b and 'period=4.000ns' in b and re.search(r'(?m)^\s+SLICE_\S+\s+FDPE\s+f\s+'+re.escape(end)+r'\s*$',b),'unexpected endpoint or clock')
        delay=float(re.match(r'(\d+\.\d+)ns',field('Data Path Delay'))[1]); rows[k]=dict(source=source,kind=kind.split()[0],data_delay_ns=delay)
    expected={(s,k) for s in ('reset','fpga_power_on/power_on_reset_reg/C') for k in ('Recovery','Removal')}
    need(set(rows)==expected,'missing reset source/check'); return dict(timing_report_sha256=OLD_TIMING,endpoint=end,paths=[rows[k] for k in sorted(rows)],slack='inf (False Path); no physical recovery/removal margin')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('checkpoint',type=Path); p.add_argument('--archived-timing',type=Path); a=p.parse_args()
    result=inspect(a.checkpoint)
    if a.archived_timing: result['original_routed_evidence']=old_paths(result['checkpoint_sha256'],a.archived_timing)
    print(json.dumps(result,indent=2))
