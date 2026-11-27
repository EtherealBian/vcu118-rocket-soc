#!/usr/bin/env python3
"""Clock both unmodified queue interfaces: compare qualifiers and valid payload, with no internal forcing."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

D=runpy.run_path(str(Path(__file__).with_name('derive-mega-miss-select.py')))
U,S=D['UNIT'],D['SLOT']

def bench(unit):
    header=unit.split('module '+U+'(',1)[1].split(');',1)[0]
    ports=re.findall(r'^  (input|output)\s+(?:\[(\d+):0\]\s*)?(\w+)\s*,?\s*(?://.*)?$',header,re.M)
    assert len(ports)==len(re.findall(r'^  (?:input|output)\s',header,re.M))
    ins=[(w,n) for direction,w,n in ports if direction=='input']; outs=[n for direction,_,n in ports if direction=='output']
    l=['module tb;', 'integer t,j,issued,rescues,both8; reg [31:0] seed; task step; begin seed=seed^(seed<<13); seed=seed^(seed>>17); seed=seed^(seed<<5); end endtask']
    for w,n in ins:l.append(f"reg {('['+w+':0]') if w else ''} {n};")
    for typ,inst in [(U,'g'),('CandidateQueue','v')]:
        l.append(f'{typ} {inst}('+','.join('.'+n+'('+n+')' for _,n in ins)+');')
    controls=[n for n in outs if not n.startswith('io_iss_uops_')];assert len(controls)==8
    def concat(prefix,names):return '{'+','.join(prefix+'.'+n for n in names)+'}'
    widths={n:int(w or 0)+1 for _,w,n in ports}
    def obs(label,names):
        width=sum(widths.get(n,1) for n in names)
        for inst in ('g','v'):l.append(f'wire [{width-1}:0] {inst}_{label} = '+concat(inst,names)+';')
    obs('control',controls);obs('moves',[f'issue_slots_{i}_in_uop_valid' for i in reversed(range(40))]);obs('keeps',[f'_slots_{i}_io_will_be_valid' for i in reversed(range(40))]);
    for i in range(4):obs('payload'+str(i),[n for n in outs if n.startswith(f'io_iss_uops_{i}_')])
    # Actual miss changes a selected move iff toggling the *external* common miss changes that wire, holding all other inputs and clock fixed.
    l+=['reg [39:0] m0; task check; begin #1; if((^g_control===1\'bx)||(^g_moves===1\'bx)||(^g_keeps===1\'bx)||g_control!==v_control||g_keeps!==v_keeps||g_moves!==v_moves) begin $display("QUEUE_CLOCK_MISMATCH t=%d",t);$finish_and_return(2);end']
    for i in range(4):l.append(f'if(g.io_iss_valids_{i} && ((^g_payload{i} === 1\'bx) || g_payload{i} !== v_payload{i})) begin $display("ISSUE_PAYLOAD_MISMATCH t=%d lane={i}",t);$finish_and_return(3);end')
    l+=['end endtask','initial begin',*(n+"='0;" for _,n in ins),"seed=32'h78aa499c; issued=0;rescues=0;both8=0;reset=1;repeat(4)begin #1;clock=1;#1;clock=0;end reset=0;",'for(t=0;t<1200;t=t+1)begin']
    for w,n in ins:
        if n in ('clock','reset','io_ld_miss'): continue
        if n.startswith('io_fu_types_'):rhs="(t%73<22)?0:10'h3ff"
        elif n=='io_flush_pipeline':rhs='(t%137==136)'
        elif n=='io_brupdate_b1_mispredict_mask':rhs='(t%43==42)?seed:0'
        elif n.endswith(('_bits_is_fence','_bits_is_fencei','_bits_exception')):rhs='(seed[5:0]==0)'
        elif n.endswith('bits_fu_code'):rhs="10'h1"
        elif n.endswith(('_bits_lrs1_rtype','_bits_lrs2_rtype')):rhs='0'
        elif n.endswith(('_bits_prs1','_bits_prs2','_bits_pdst')) or re.search(r'spec_ld_wakeup_\d+_bits$',n):rhs='1+seed[1:0]'
        elif n.startswith('io_wakeup_ports_') and n.endswith('_valid'):rhs='(seed[3:0]==0)'
        elif n.endswith('_valid') and n.startswith('io_dis_uops_'):rhs='seed[0] && g.'+n.replace('_valid','_ready')
        else:rhs="{seed,seed[31:16]}" if w and int(w)>=32 else 'seed'
        l.append('step; '+n+'='+rhs+';')
    l+=['io_ld_miss=0;check;m0=g_moves;io_ld_miss=1;check;for(j=0;j<40;j=j+1) if(m0[j]!=g_moves[j])rescues=rescues+1;if(m0[8]!=g_moves[8])both8=both8+1;', 'step;io_ld_miss=seed[0];check;', 'issued=issued+'+'+'.join(f'g.io_iss_valids_{i}' for i in range(4))+';clock=1;check;clock=0;#1;end', 'if(issued<200 || rescues==0 || both8==0)begin $display("INSUFFICIENT %d %d %d",issued,rescues,both8);$finish_and_return(4);end', '$display("QUEUE_CLOCKED_MATCH 1200 %0d %0d %0d",issued,rescues,both8);$finish_and_return(0);end endmodule','']
    return '\n'.join(l)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('kit',type=Path);ap.add_argument('out',type=Path);ap.add_argument('icarus_root',type=Path);a=ap.parse_args();r=a.icarus_root.resolve()/'usr';lib=r/'lib/x86_64-linux-gnu/ivl';out=a.out.resolve();out.mkdir();src=D['sealed'](a.kit);alt=D['derive'](src);tb=bench(src[U]);(out/'tb.sv').write_bytes(tb.encode());(out/'stock.sv').write_bytes(src[U].encode());(out/'slot.sv').write_bytes(src[S].encode());results={}
    for label,raw in [('candidate',alt),('cross_slot9',D['one'](alt,"next_8 == 4'h1 & vcu_poison_9;","next_8 == 4'h1 & vcu_poison_10;"))]:
        (out/(label+'.sv')).write_bytes(D['one'](raw,'module '+U+'(','module CandidateQueue(').encode());cmd=[r/'bin/iverilog','-B',lib,'-g2012','-DSYNTHESIS','-s','tb','-o',label+'.vvp','slot.sv','stock.sv',label+'.sv','tb.sv'];
        with (out/(label+'.compile')).open('wb') as f:subprocess.run(cmd,cwd=out,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=240)
        p=subprocess.run([r/'bin/vvp','-M',lib,label+'.vvp'],cwd=out,capture_output=True,text=True,timeout=240);log=p.stdout+p.stderr;(out/(label+'.log')).write_text(log)
        if label=='candidate':
            m=re.fullmatch(r'QUEUE_CLOCKED_MATCH 1200 (\d+) (\d+) (\d+)\s*',log);D['need'](p.returncode==0 and m,'clocked test failed: '+log[-320:]);results.update(dict(zip(('issue_valid_lane_samples','miss_sensitive_move_samples','slot8_sensitive_samples'),map(int,m.groups()))))
        else:
            m=re.fullmatch(r'QUEUE_CLOCK_MISMATCH t=\s*(\d+)\s*',log);D['need'](p.returncode==2 and m,'negative not seen: '+log[-320:]);results['cross_slot9_rejected_cycle']=int(m[1])
    results.update(scope='1200 artificial queue clocks, no forced internals. Four-state comparison of known qualifiers and valid issued payloads, move/keep controls before/after active clock; both miss levels probed between clocks. Not a workload or full-CPU test.',candidate_sha256=hashlib.sha256(alt.encode()).hexdigest(),fixture_sha256=hashlib.sha256(tb.encode()).hexdigest());(out/'result.json').write_bytes((json.dumps(results,indent=2)+'\n').encode());print('INT_QUEUE_CLOCKED_MATCH_AND_NEGATIVE_COMPLETE')
if __name__=='__main__':main()
