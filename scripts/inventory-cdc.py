#!/usr/bin/env python3
"""Inventory every detailed Vivado CDC row; group known critical endpoints, never waive them."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def family(row):
    src, dst, rule = row['from'], row['to'], row['rule']
    if rule=='CDC-7' and dst=='dutWrangler/deglitched_deglitch/reg_0_reg/PRE' and src in ('mig/island/blackbox/inst/div_clk_rst_r1_reg/C','mig/island/blackbox/inst/u_ddr4_mem_intfc/u_ddr_mc/rst_r1_reg/C','fpga_power_on/power_on_reset_reg/C'):
        return 'MIG/POR to reset-wrangler asynchronous preset'
    if rule=='CDC-10' and re.search(r'/(?:source|sink)_valid_0/io_out_sink_valid_0/output_chain/sync_2_reg/CLR$',dst):
        if dst.startswith('chiptop0/system/tlDM/'): return 'DMI async queue validity reset'
        if dst.startswith(('mig/axi4asource/','mig/island/axi4asink/')): return 'DDR AXI async queue validity reset'
    if rule=='CDC-11' and src=='chiptop0/system/tlDM/dmOuter/dmOuter/DMCONTROLReg_dmactive_reg/C' and dst in ('chiptop0/dmactiveAck_dmactiveAck/output_chain/sync_2_reg/D','chiptop0/system/tlDM/dmInner/dmactive_synced_dmactive_synced_dmactiveSync/output_chain/sync_2_reg/D'):
        return 'dmactive request received by two synchronizers'
    if rule=='CDC-13' and src=='chiptop0/system/tlDM/dmOuter/dmOuter/debugIntRegs_0_reg/C' and re.fullmatch(r'chiptop0/system/tile_prci_domain/intsink/chain/output_chain/sync_\d+_reg_srl\d+/D',dst):
        return 'debug interrupt enters tile through a shift LUT'
    return 'unclassified'


def inventory(text):
    summary={}; counts=Counter(); rows=[]; src=dst=kind=None; last=0
    for line in text.splitlines():
        m=re.match(r'^(CDC-\d+)\s+(Critical|Warning|Info)\s+(\d+)\s+',line)
        if m:
            key=(m[1],m[2]);
            if key in summary: raise ValueError('duplicate summary '+str(key))
            summary[key]=int(m[3]); continue
        if line.startswith('Source Clock: '): src=line[14:]; dst=kind=None; last=0; continue
        if line.startswith('Destination Clock: '): dst=line[19:]; continue
        if line.startswith('CDC Type: '): kind=line[10:]; continue
        if not re.match(r'^\s*\d+\s+CDC-',line): continue
        col=re.split(r'\s{2,}',line.strip());
        if len(col)!=8 or not all((src,dst,kind)) or int(col[0])!=last+1: raise ValueError('invalid or missing detail row: '+line)
        last+=1; _, rule, severity, _, depth, exception, launch, capture=col
        counts[(rule,severity)]+=1
        row=dict(rule=rule,severity=severity,source_clock=src,destination_clock=dst,crossing=kind,depth=int(depth),exception=exception);row.update({'from':launch,'to':capture})
        if severity=='Critical': row['family']=family(row)
        rows.append(row)
    if not counts or summary!=counts: raise ValueError('summary and detail counts disagree or report is empty')
    critical=[r for r in rows if r['severity']=='Critical']
    return dict(total_rows=len(rows),counts={f'{r} {s}':n for (r,s),n in sorted(counts.items())},critical=critical,
                critical_families=dict(Counter(r['family'] for r in critical)),disposition='inventory only; no CDC, timing, I/O or board signoff')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('cdc_report',type=Path);a=p.parse_args()
    raw=a.cdc_report.read_bytes(); result=inventory(raw.decode()); result['input_sha256']=hashlib.sha256(raw).hexdigest()
    print(json.dumps(result,indent=2))
