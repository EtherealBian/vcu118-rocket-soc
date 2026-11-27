#!/usr/bin/env python3
"""Exercise the two actual AXI AW async queue halves, including unilateral reset while live."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
TB = HERE.parent/'tests/mega_aw_reset_tb.sv.in'
S = 'AsyncQueueSource_AXI4BundleAW'
D = 'AsyncQueueSink_AXI4BundleAW'
UNITS = [S,D,'AsyncValidSync','AsyncResetSynchronizerShiftReg_w1_d3_i0_2',
         'AsyncResetSynchronizerShiftReg_w4_d3_i0','AsyncResetSynchronizerPrimitiveShiftReg_d3_i0','ClockCrossingReg_w61']
FIELDS = {'id':4, 'addr':32, 'len':8, 'size':3, 'burst':2, 'lock':1, 'cache':4, 'prot':3, 'qos':4}
NUMBERS = [(2857,2500,113), (2857,2500,1569), (2500,2857,479), (2101,4591,151)]
SEALS = ['b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959',
         'ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456']
h = lambda b:hashlib.sha256(b).hexdigest()


def connections():
    lines = []; ports = [[], []]
    for i in range(8):
        lines.append(f'wire [60:0] m{i};')
    for index,(unit,clk,rst,data,side) in enumerate([(S,'sc','sr','datain','enq'),(D,'dc','dr','dataout','deq')]):
        p=ports[index]; p.extend([('clock',clk),('reset',rst),('io_'+side+'_valid',('send','devalid')[index]),('io_'+side+'_ready',('enready','take')[index])]);
        high=60
        for name,w in FIELDS.items():
            bits=f'[{high}:{high-w+1}]'; high-=w
            if index == 1 and name == 'cache':
                # This physical sink prunes the cache output port; observe that lane of its actual registered payload.
                lines.append('assign dataout[10:7] = dst._io_deq_bits_deq_bits_reg_io_q[10:7];')
            else:
                p.append(('io_'+side+'_bits_'+name,data+bits))
            p.extend((f'io_async_mem_{i}_'+name,f'm{i}'+bits) for i in range(8))
        assert high == -1
        p.extend(('io_async_'+k,v) for k,v in [('ridx','ri'),('widx','wi'),('safe_ridx_valid','rv'),('safe_widx_valid','wv'),('safe_source_reset_n','ssn'),('safe_sink_reset_n','rsn')]);
        lines.append(unit+' '+('src','dst')[index]+'('+',\n'.join(f'.{k}({v})' for k,v in p)+');')
    return '\n'.join(lines)


def bench():
    return TB.read_text().replace('// AW_DUT', connections())


def run(stock, candidate, out, tool):
    if [h((k/'CANDIDATE.sha256').read_bytes()) for k in (stock,candidate)] != SEALS: raise ValueError('wrong pair')
    check=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']; a,b=check(stock),check(candidate)
    members={u:a['rtl/'+u+'.sv'] for u in UNITS}
    if any(b['rtl/'+u+'.sv']!=v for u,v in members.items()): raise ValueError('AW RTL changed')
    if out.exists() or any(k in out.parents or out in k.parents for k in (stock,candidate)): raise ValueError('fresh disjoint output required')
    out.mkdir(); tb=out/'tb.sv'; tb.write_text(bench()); lib=tool/'usr/lib/x86_64-linux-gnu/ivl'; bindir=tool/'usr/bin'
    findings={}; negatives={}
    for case in ('unaltered','omit_remote_at_source_first','omit_remote_at_sink_first'):
        rtl=[candidate/'rtl'/(u+'.sv') for u in UNITS]
        if case!='unaltered':
            i=int('at_sink' in case); inst=('source_valid_0','sink_valid_0')[i]; remote=('sink','source')[i]
            raw=rtl[i].read_text(); start=raw.index('  AsyncValidSync '+inst+' ('); end=raw.index(');',start); block=raw[start:end]
            pattern='(reset | ~io_async_safe_'+remote+'_reset_n)'; assert block.count(pattern)==1
            f=out/(case+'.sv'); f.write_text(raw[:start]+block.replace(pattern,'(reset)')+raw[end:]); rtl[i]=f
        exe=out/(case+'.vvp'); subprocess.run([bindir/'iverilog','-B',lib,'-g2012','-DSYNTHESIS','-s','tb','-o',exe,tb,*rtl],check=True)
        for hs,hd,ph in NUMBERS:
            key=f'{hs}-{hd}-{ph}'; proc=subprocess.run([bindir/'vvp','-M',lib,exe,f'+HS={hs}',f'+HD={hd}',f'+PH={ph}'],capture_output=True,text=True,timeout=15)
            text=proc.stdout+proc.stderr; (out/(case+'-'+key+'.log')).write_text(text)
            if case=='unaltered':
                match=re.search(r'^AW_RESULT sink_reset_enqueues=(\d+) source_reset_dequeues=(\d+) drained=81 outstanding_at_reset=6$',text,re.M)
                if proc.returncode or not match or 'FATAL:' in text: raise ValueError(case+' '+key+': '+text[:300])
                findings[key]=dict(zip(('sink_reset_enqueues_before_isolation','source_reset_dequeues_before_isolation'),map(int,match.groups())))
            else:
                if proc.returncode!=3 or 'VALID_LATENCY' not in text or 'AW_RESULT' in text: raise ValueError('wrong negative outcome '+case+' '+key+': '+text[:300])
                negatives.setdefault(case,[]).append(key)
    return dict(scope='Four-state AW queue RTL only. Independent resets deliberately exercised under live traffic, not evidence of board reset reachability or analog CDC safety.',
                kits=SEALS,units_sha256=members,bench_sha256=h(tb.read_bytes()),half_periods_and_sink_phase_ps=findings,
                clean_ordered_transfers_per_case=81,outstanding_before_source_reset=6,unilateral_reset_ps=800,negative_controls_rejected=negatives)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('stock','candidate','out','icarus_root'): p.add_argument(n,type=Path)
    a=p.parse_args(); result=run(*(getattr(a,n).resolve() for n in ('stock','candidate','out','icarus_root')))
    text=json.dumps(result,indent=2)+'\n'; (a.out/'result.json').write_text(text); print(text,end='')
