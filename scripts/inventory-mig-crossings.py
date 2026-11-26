#!/usr/bin/env python3
"""Account for ignored system/UI timing endpoints in a routed VCU118 design (not STA signoff)."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re

SYS='clk_out1_harnessSysPLL'; UI='mmcm_clkout0'
SYSQ='mig/axi4asource/'; UIQ='mig/island/axi4asink/'
SYS_RESET='dutWrangler/nodeOut_reset_catcher/io_sync_reset_chain/output_chain/sync_0_reg/C'
MIG_RESETS={'mig/island/blackbox/inst/'+s+'/C' for s in ('div_clk_rst_r1_reg','u_ddr4_mem_intfc/u_ddr_mc/rst_r1_reg','u_ddr4_mem_intfc/u_ddr_cal_top/rst_r1_reg')}
VALID='io_out_sink_valid_0/output_chain/'


def classify(clock, start, end):
    forward=clock==SYS; src,dst=(SYSQ,UIQ) if forward else (UIQ,SYSQ)
    for ch in ('ar','aw','w','b','r'):
        send=ch in ('ar','aw','w'); send_fwd=(send==forward); node=('nodeOut_' if send else 'nodeIn_')+ch
        s=src+node+('_source/' if send_fwd else '_sink/'); d=dst+node+('_sink/' if send_fwd else '_source/')
        if not (start.startswith(s) and end.startswith(d)): continue
        a=start[len(s):]; b=end[len(d):]; idx='widx' if send_fwd else 'ridx'
        m=re.fullmatch(idx+r'_gray_reg\[([0-3])\]/C',a)
        if m:
            bit=int(m[1]); chain='output_chain'+(f'_{bit}' if bit else '')
            if b==f'{idx}_{idx}_gray/{chain}/sync_2_reg/D': return 'gray'
        if send_fwd and re.fullmatch(r'mem_[0-7]_(?:addr|size|id|len|data|strb|last|resp)_reg(?:\[\d+\])?/C',a) and re.fullmatch(r'io_deq_bits_deq_bits_reg/cdc_reg_reg(?:\[\d+\])?/D',b): return 'payload'
    srst=start==SYS_RESET if forward else start in MIG_RESETS
    sb=src+('nodeOut_aw_source/source_valid_1/' if forward else 'nodeOut_aw_sink/sink_valid_1/')+VALID
    dv=dst+('nodeOut_aw_sink/' if forward else 'nodeIn_b_sink/')+'source_extend/'+VALID
    if start==sb+'sync_0_reg/C' and end==dv+'sync_2_reg/D': return 'valid_data'
    if srst and end.startswith(dst):
        pre=(r'nodeOut_aw_sink/(?:sink_valid_[01]|source_extend)' if forward else r'(?:nodeIn_b_sink/source_extend|nodeOut_aw_source/source_valid_[01])')
        if re.fullmatch(pre+'/'+VALID+r'sync_[0-2]_reg/CLR',end[len(dst):]): return 'valid_reset'
    if forward and start=='dutWrangler/deglitched_deglitch/reg_0_reg/C' and re.fullmatch(r'dutWrangler/nodeOut_reset_catcher_1/io_sync_reset_chain/output_chain/sync_[0-2]_reg/CLR',end): return 'wrangler_release_reset'
    if not forward and srst:
        if end=='dutWrangler/deglitched_deglitch/reg_0_reg/PRE': return 'wrangler_preset'
        if re.fullmatch(r'dutWrangler/debounced_debounce/reg_0_reg\[(?:[0-9]|1[0-3])\]/CLR',end): return 'wrangler_counter_reset'
    raise ValueError('unreviewed ignored path: '+start+' -> '+end)


def inventory(tsv, interaction):
    reader=csv.DictReader(io.StringIO(tsv),delimiter='\t'); pairs={(SYS,UI):{},(UI,SYS):{}}; result={}
    if reader.fieldnames!=['source_clock','destination_clock','kind','start','end','datapath_ns','logic_levels']:raise ValueError('unrecognized columns')
    for row in reader:
        key=row['source_clock'],row['destination_clock']; kind=row['kind']
        if key not in pairs or kind not in ('max','min'):raise ValueError('unrecognized clock direction or corner')
        rec=pairs[key].setdefault(kind,{}); end=row['end']; delay=float(row['datapath_ns'])
        if end in rec or not math.isfinite(delay) or delay<0 or int(row['logic_levels'])<0: raise ValueError('duplicate endpoint or invalid numeric field')
        rec[end]=(classify(key[0],row['start'],end),delay)
    for (src,dst),corners in pairs.items():
        counts=re.findall(r'^'+re.escape(src)+r'\s+'+re.escape(dst)+r'\s+0\s+(\d+)\s+Ignored\s+Asynchronous Groups\s*$',interaction,re.M)
        if len(counts)!=1 or set(corners)!={'max','min'} or len(corners['max'])!=int(counts[0]) or corners['max'].keys()!=corners['min'].keys(): raise ValueError('endpoint/clock interaction counts do not reconcile: '+src+' -> '+dst)
        classes={}; peaks={}
        for end,(f,delay) in corners['max'].items():
            if corners['min'][end][0]!=f:raise ValueError('inconsistent capture classification')
            classes[f]=classes.get(f,0)+1; peaks[f]=max(delay,peaks.get(f,0.0))
        result[src+' -> '+dst]=dict(endpoints=len(corners['max']),captures=classes,max_reported_datapath_ns=peaks)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('tsv',type=Path);p.add_argument('interaction',type=Path);a=p.parse_args()
    data=[x.read_bytes() for x in (a.tsv,a.interaction)]
    print(json.dumps({'directions':inventory(*(x.decode() for x in data)), 'input_sha256':[hashlib.sha256(x).hexdigest() for x in data],
        'scope':'One max and one min path per ignored endpoint. Not every launch/capture pair, skew, routed slack or a CDC waiver.'},indent=2))
if __name__=='__main__': main()
