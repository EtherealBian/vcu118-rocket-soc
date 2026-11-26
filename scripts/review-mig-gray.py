#!/usr/bin/env python3
"""Reconcile diagnostic Vivado bus-skew constraints with all 40 physical Gray bits."""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re

SYS, UI = 'clk_out1_harnessSysPLL', 'mmcm_clkout0'
CHANNELS = ('aw', 'w', 'b', 'ar', 'r')
GROUPS = {(ch,p) for ch in CHANNELS for p in ('ridx','widx')}

def rows(text, cols):
    reader = csv.DictReader(io.StringIO(text), delimiter='\t')
    if reader.fieldnames != cols.split(): raise ValueError('wrong TSV header')
    return reader

def analyze(bits, delays, report):
    report=report.replace('\r\n','\n'); groups={k:{} for k in GROUPS}; times={}
    for row in rows(bits, 'channel pointer bit launch_clock capture_clock launch capture'):
        ch,p = row['channel'],row['pointer']; i=int(row['bit']); group=groups[ch,p]; outgoing=ch in ('aw','ar','w'); write=p=='widx'; forward=outgoing==write
        node=('nodeOut_' if outgoing else 'nodeIn_')+ch; sb,db=('mig/axi4asource','mig/island/axi4asink') if forward else ('mig/island/axi4asink','mig/axi4asource')
        src=sb+'/'+node+('_source' if write else '_sink')+'/'+p+f'_gray_reg[{i}]'
        dst=db+'/'+node+('_sink' if write else '_source')+'/'+p+'_'+p+'_gray/output_chain'+(f'_{i}' if i else '')+'/sync_2_reg'
        if not 0<=i<4 or i in group or (row['launch'],row['capture'])!=(src,dst) or (row['launch_clock'],row['capture_clock'])!=((SYS,UI) if forward else (UI,SYS)): raise ValueError('wrong or duplicate pointer connection')
        group[i]=(src,dst)
    if any(set(g)!=set(range(4)) for g in groups.values()): raise ValueError('incomplete pointer inventory')
    for row in rows(delays, 'channel pointer bit corner data_ns logic_levels'):
        ch,p,i,k=row['channel'],row['pointer'],int(row['bit']),row['corner']; key=(ch,p,i,k); delay=float(row['data_ns'])
        if i not in groups[ch,p] or k not in ('min','max') or key in times or row['logic_levels']!='0' or not math.isfinite(delay) or delay<0: raise ValueError('invalid data-path entry')
        times[key]=delay
    if len(times)!=80 or any(times[ch,p,i,'min']>times[ch,p,i,'max'] for ch,p in GROUPS for i in range(4)): raise ValueError('incomplete or inconsistent corner delays')
    if not re.search(r'Design State\s*:\s*Physopt postRoute\b',report): raise ValueError('not a post-route report')
    found={}
    for section in re.split(r'^Id:\s*\d+\s*$',report,flags=re.M)[1:]:
        x=re.search(r'^set_bus_skew -from (.*?) -to (.*?) ([\d.]+)$',section,re.M)
        if not x: raise ValueError('unknown skew constraint')
        if 'mig/' not in x[0]:
            if 'dbg_hub/' not in x[1] or 'dbg_hub/' not in x[2]: raise ValueError('unexpected other constraint')
            continue
        matched=[k for k,g in groups.items() if all(src in x[1] and dst in x[2] for src,dst in g.values())]
        if len(matched)!=1 or matched[0] in found or float(x[3])!=5 or x[1].count('mig/')!=4 or x[2].count('mig/')!=4 or not re.search(r'^Endpoints:\s+4\s*$',section,re.M): raise ValueError('wrong transfer membership, budget or coverage')
        key=matched[0]; ch,p=key; group=groups[key]; paths=re.split(r'^Slack \((MET|VIOLATED)\)\s*:\s*([-\d.]+)ns[^\n]*',section,flags=re.M)[1:]
        if len(paths)!=12: raise ValueError('expected a worst report row for each of four captures')
        endpoint_ids=set(); signed=[]; slacks=[]
        for status, slack, detail in zip(paths[::3],paths[1::3],paths[2::3]):
            for prefix in ('Endpoint','Reference'):
                def cell_at(pin,suffix):
                    m=re.search(r'^  '+prefix+' '+pin+r':\s+(\S+)'+suffix+r'\s*$',detail,re.M)
                    if not m: raise ValueError('missing detail pin')
                    return m[1]
                pair=(cell_at('Source','/C'),cell_at('Destination','/D'))
                if pair not in group.values(): raise ValueError('bit path mismatch')
                if prefix=='Endpoint': endpoint_ids.add(pair)
            m=re.search(r'^  Actual Bus Skew:\s*([-\d.]+)ns',detail,re.M); s=float(slack)
            if not m or abs(5-float(m[1])-s)>.002 or ((status=='MET') != (s>=0)): raise ValueError('unreconciled skew result')
            signed.append(float(m[1])); slacks.append(s)
        if endpoint_ids!=set(group.values()): raise ValueError('duplicate or missing skew endpoint')
        found[key]={'minimum_reported_skew_slack_ns':min(slacks),'largest_signed_vendor_skew_ns':max(signed),'min_data_ns':min(times[ch,p,i,'min'] for i in group),'max_data_ns':max(times[ch,p,i,'max'] for i in group)}
    if found.keys()!=GROUPS: raise ValueError('missing skew group')
    return {ch+':'+p:found[ch,p] for ch,p in sorted(found)}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('folder',type=Path);a=ap.parse_args();files={n:(a.folder/n).read_bytes() for n in ('bits.tsv','data-delays.tsv','bus-skew.rpt')}
    print(json.dumps({'transfers':analyze(*(b.decode() for b in files.values())),'input_sha256':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()},'scope':'Temporary 5 ns bus-skew characterization on an already routed design, not an implemented constraint, CDC waiver, guaranteed MTBF or hardware calibration. Signed vendor skew is not a physical one-way flight time.'},indent=2))
if __name__=='__main__':main()
