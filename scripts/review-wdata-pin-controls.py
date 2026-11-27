#!/usr/bin/env python3
"""Trace the four initial-route WDATA pins in two independently bound historical SDF/netlist pairs."""
import argparse
from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
import json
import mmap
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
AW = runpy.run_path(str(HERE/'review-aw-control-fanout.py'))
DOCS, TOP, need, digest = (AW[k] for k in ('DOCS','TOP','need','digest'))
QUEUE = 'mig/toaxi4/nodeOut_w_deq_q/'
W = 'mig/axi4asource/nodeOut_w_source/'
DATA = re.compile(re.escape(W)+r'mem_([0-7])_data_reg\[(\d+)\]/D')
FILES = ('XilinxVCU118MIG','TLToAXI4','Queue1_AXI4BundleW','AXI4AsyncCrossingSource','AsyncQueueSource_AXI4BundleW')


def mux(b):
    return QUEUE+f'mem_0_data[{b}]_i_{2 if b==63 else 1}'


def pin(slot, b):
    return W+f'mem_{slot}_data_reg[{b}]/D'


def load_pins(path, ref):
    raw=path.read_bytes(); need(sha256(raw).hexdigest()==ref['native_tight_pins_sha256'],'different native four-wide pin table')
    rows=[tuple(c.strip() for c in line.strip('|').split('|')) for line in raw.decode().splitlines() if line.startswith('|')][1:]
    need(len(rows)==ref['pins']==len({p for _,_,p in rows}) and all(a==b==ref['launch_setup_and_hold_clocks'] for a,b,_ in rows),'pin count, duplicate, or clock')
    observed=sorted((int(m[1]),int(m[2])) for _,_,p in rows if (m:=DATA.fullmatch(p)))
    need(observed==[(1,5),(3,5),(6,5),(7,5)] and len(observed)==ref['pin_families']['mig_axi_w_source_data'],'different W pins')
    return observed


def sources(kit, seal):
    manifest=kit/'CANDIDATE.sha256'; need(digest(manifest)==seal,'unbound kit')
    rows=manifest.read_text().splitlines(); hashes={}
    for name in FILES:
        path=f'rtl/{name}.sv'; h=digest(kit/path); need(rows.count(f'{h}  {path}')==1,'source not sealed');hashes[name]=h
    return hashes


def module(mm,name):
    found=list(re.finditer(rb'^module '+name.encode()+rb'\r?$',mm,re.M)); need(len(found)==1,'missing or duplicate '+name)
    lo=found[0].end(); hi=mm.find(b'\nendmodule',lo);need(hi>lo,'truncated module');return mm[lo:hi].decode('ascii')


def check_verilog(path):
    with path.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
        q=module(mm,'Queue1_AXI4BundleW'); w=module(mm,'AsyncQueueSource_AXI4BundleW')
    check_verilog_text(q,w)


def check_verilog_text(q,w):
    gates=re.findall(r"^  LUT3 #\(\s*\.INIT\(8'h([0-9A-Fa-f]{2})\)\)\s+\\(mem_0_data\[\d+\]_i_\d+)\s+\(",q,re.M)
    names={mux(b)[len(QUEUE):] for b in range(64)}; chosen=[(n,int(init,16)) for init,n in gates if n in names]
    need(len(chosen)==64 and set(dict(chosen))==names,'missing mapped data selector')
    for _,init in chosen:
        for i in range(8):need((init>>i)&1 == ((i&1) if i&2 else ((i>>2)&1)),'not stored-data/full/bypass mux')
    flops=re.findall(r'^  FDRE \\mem_([0-7])_data_reg\[(\d+)\]\s+\(([^;]+)\);',w,re.M)
    need(len(flops)==512 and {(int(s),int(b)) for s,b,_ in flops}=={(s,b) for s in range(8) for b in range(64)},'missing W payload FDRE')
    ds=defaultdict(set)
    for s,b,ports in flops:
        d=re.findall(r'\.D\(([^)]+)\)',ports); need(len(d)==1,'missing data port');ds[int(b)].add(d[0].strip())
    need(all(len(n)==1 for n in ds.values()) and len(set.union(*ds.values()))==64,'not 64 distinct common D buses')


def sdf(path):
    arcs={}; h=sha256()
    with path.open('rb',buffering=1<<20) as f:
        header=b''.join(f.readline() for _ in range(9));h.update(header)
        need({r.strip() for r in header.splitlines()}>={b'(TIMESCALE 1ps)',b'(VERSION "2024.2")',f'(DESIGN "{TOP}")'.encode()},'wrong SDF scope')
        for row in f:
            h.update(row)
            if b'(INTERCONNECT ' not in row or not (b'nodeOut_w_deq_q/mem_0_data' in row or b'nodeOut_w_source/mem_' in row):continue
            m=AW['ARC'].fullmatch(row.strip().decode('ascii').replace('\\',''));need(m,'unknown selected SDF wire')
            src,dst=m[1],m[2];need((src,dst) not in arcs,'duplicate selected SDF wire');arcs[src,dst]=max(Decimal(m[5]),Decimal(m[8]))
    return arcs,h.hexdigest()


def span(vals): return [str(min(vals)),str(max(vals))]


def trace(arcs, observed):
    incoming=defaultdict(list);outgoing=defaultdict(dict)
    for (src,dst),delay in arcs.items():incoming[dst].append((src,delay));outgoing[src][dst]=delay
    per_bit={}; data=[]; roles=defaultdict(list);selected={}; bypass_longer=0
    for b in range(64):
        gate=mux(b); driven=outgoing[gate+'/O']; want={pin(s,b) for s in range(8)}
        need(set(driven)==want and all(len(incoming[d])==1 for d in want),'unexpected physical data fanout or multiple D drivers')
        wires={}
        for i,role in enumerate(('stored','full_select','bypass')):
            inp=incoming[gate+'/I'+str(i)];need(len(inp)==1,'missing or duplicate physical mux input');src,delay=inp[0]
            expected=(src==QUEUE+f'ram_reg[{b}]/Q',src==QUEUE+'full_reg/Q',src.startswith('mig/buffer/nodeOut_a_q/ram_ext/') and src.endswith('/O'))
            need(expected[i],'wrong physical selector input '+role);roles[role].append(delay);wires[role]=str(delay)
        per_bit[b]=max(driven.values());data.extend(driven.values())
        bypass_longer+=roles['bypass'][-1]>per_bit[b]
        if b==5:selected=dict(input_wire_max_ps=wires,eight_output_wire_max_ps_range=span(driven.values()),tight_output_wire_max_ps_by_slot={str(s):str(driven[pin(s,b)]) for s,k in observed if k==b})
    return dict(data_bits=64,queue_slots=8,mapped_data_D_pins=len(data),data_muxes=64,output_sinks_per_mux=8,all_output_wire_max_ps_range=span(data),input_wire_max_ps_ranges={k:span(v) for k,v in roles.items()},bit5=selected,
                bits_with_bypass_wire_longer_than_all_eight_output_wires=bypass_longer,
                other_bits_with_larger_worst_output_wire=sum(v>per_bit[5] for v in per_bit.values()))


def review(fourkit, table, controls):
    ref=json.loads((DOCS/'perf-mega175-initial-congestion.json').read_bytes()); archive=json.loads((DOCS/'perf-aw-routed-controls.json').read_bytes()); slots=load_pins(table,ref); common=sources(fourkit,ref['board_input_seal'])
    out={}
    for name,(run,kit) in controls.items():
        saved=archive[name]; stem=run/'obj'/TOP;bit=digest(stem.with_suffix('.bit'));need(bit==saved['bit_sha256'],'different control build')
        paths=run/'sources.windows.f'; manifest=digest(kit/'CANDIDATE.sha256');need(sources(kit,manifest)==common,'different W channel RTL')
        filelist=paths.read_text().splitlines();need(all(sum(x.endswith('/'+kit.name+'/rtl/'+n+'.sv') for x in filelist)==1 for n in FILES),'unbound W RTL in run')
        v=stem.with_suffix('.v');check_verilog(v);edges,sh=sdf(stem.with_suffix('.sdf'));AW['bind'](bit,(digest(v),sh,manifest,digest(paths)))
        clocks=(run/'obj/report/routed-clocks.rpt').read_text();need(re.findall(r'^clk_out1_harnessSysPLL\s+([\d.]+)\s+\{',clocks,re.M)==['10.000'],'wrong control clock')
        out[name]=dict(bit_sha256=bit,sdf_sha256=sh,**trace(edges,slots))
    return dict(scope='Two historical 100 MHz routed controls; each SDF wire reports the larger rising/falling MAX in ps. No arc sums, four-wide slack, or board score.',four_wide_input_seal=ref['board_input_seal'],four_wide_pin_table_sha256=ref['native_tight_pins_sha256'],shared_W_source_sha256=common,controls=out)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('fourkit','pin_table','rocket_run','rocket_kit','medium_run','medium_kit'):p.add_argument(k,type=Path)
    a=p.parse_args();print(json.dumps(review(a.fourkit,a.pin_table,{'rocket':(a.rocket_run,a.rocket_kit),'two_wide_boom_withheld_from_board':(a.medium_run,a.medium_kit)}),indent=2))
