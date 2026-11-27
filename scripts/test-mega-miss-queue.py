#!/usr/bin/env python3
"""Check move/keep in both full integer queues with controlled resident state, not a CPU simulation."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess

D=runpy.run_path(str(Path(__file__).with_name('derive-mega-miss-select.py')))
UNIT,SLOT=D['UNIT'],D['SLOT']

def fixture(unit):
    head=unit.partition('module '+UNIT+'(')[2].partition(');')[0]
    inputs=re.findall(r'^  input\s+(?:\[(\d+):0\]\s*)?(\w+)\s*,?\s*(?://.*)?$',head,re.M)
    D['need'](len(inputs)==len(re.findall(r'^  input\s',head,re.M)) and inputs[-1][1]=='io_ld_miss','unparsed inputs')
    lines=['module tb;','reg [39:0] filled, p1bad, p2bad; integer d,k,j,lane,kind,edges;']
    for w,n in inputs: lines.append('reg '+('['+w+':0] ' if w else '')+n+';')
    bindings=','.join('.'+n+'('+n+')' for _,n in inputs)
    for inst,typ in [('g',UNIT),('v','CandidateQueue')]:
        lines.append(f'{typ} {inst}({bindings});');
        for label,t in [('moves','issue_slots_{i}_in_uop_valid'),('keeps','_slots_{i}_io_will_be_valid')]:
            lines.append(f'wire [39:0] {inst}_{label} = {{'+','.join(inst+'.'+t.format(i=i) for i in reversed(range(40)))+'};')
    lines+=['task check; begin #1; if ((^g_moves === 1\'bx) || (^g_keeps === 1\'bx) || g_moves !== v_moves || g_keeps !== v_keeps) begin $display("QUEUE_MISMATCH d=%d k=%d miss=%d",d,k,io_ld_miss); $finish_and_return(2); end end endtask','initial begin']
    lines += [n+"='0;" for _,n in inputs]
    for i in range(40):
        # All grants high is legal as an abstract cone stress, not an executable schedule.
        for inst in ('g','v'):
            lines+=[f"force {inst}.slots_{i}.state = {{1'b0,filled[{i}]}};",f'force {inst}.issue_slots_{i}_grant = 1\'b1;',f'force {inst}.slots_{i}.p1_poisoned = p1_{i};',f'force {inst}.slots_{i}.p2_poisoned = p2_{i};']
    lines += ['edges=0; for(d=0;d<40;d=d+1) for(k=1;k<=4;k=k+1) begin', "filled='1; p1bad=0; p2bad=0;",'if(d+k<40) begin for(j=d;j<d+k;j=j+1) filled[j]=0; end else begin for(j=40-k;j<40;j=j+1) filled[j]=0; end',"{io_dis_uops_3_valid,io_dis_uops_2_valid,io_dis_uops_1_valid,io_dis_uops_0_valid}=4'hf;",'if(d+k<40) for(kind=0;kind<2;kind=kind+1) begin', 'p1bad=0; p2bad=0; if(kind==0) p1bad[d+k]=1; else p2bad[d+k]=1;', 'io_ld_miss=0;check; if(g_moves[d]!==0) $fatal(1,"bad low d=%d k=%d",d,k);','io_ld_miss=1;check; if(g_moves[d]!==1) $fatal(1,"bad rescue d=%d k=%d",d,k);','io_ld_miss=0;check; if(g_moves[d]!==0) $fatal(1,"bad clear");edges=edges+1;end', 'else begin io_ld_miss=0;check; if(g_moves[d]!==1) $fatal(1,"dispatch not selected d=%d k=%d",d,k); io_ld_miss=1;check; if(g_moves[d]!==1) $fatal(1,"dispatch changed");lane=d+k-40; case(lane)']
    for i in range(4):lines.append(f'{i}: io_dis_uops_{i}_bits_exception=1;')
    lines+=['endcase check; if(g_moves[d]!==0) $fatal(1,"dispatch not suppressed d=%d k=%d",d,k);',"{io_dis_uops_3_bits_exception,io_dis_uops_2_bits_exception,io_dis_uops_1_bits_exception,io_dis_uops_0_bits_exception}=0;end end",'if(edges!=300) $fatal; $display("QUEUE_COMBINATIONAL_MATCH_300_RESCUES_10_DISPATCH"); $finish;end endmodule','']
    # Continuous nets for Icarus procedural force (expression RHS otherwise samples once).
    for i in range(40):
        tag=f"{{1'b0,filled[{i}]}}"; lines=[x.replace('= '+tag+';',f'= st_{i};') for x in lines];lines.insert(2,f'wire p1_{i} = p1bad[{i}]; wire p2_{i} = p2bad[{i}]; wire [1:0] st_{i} = '+tag+';')
    return '\n'.join(lines)

def run(a):
    orig=D['sealed'](a.kit);alt=D['derive'](orig); out=a.out.resolve();out.mkdir();tb=fixture(orig[UNIT]);(out/'tb.sv').write_bytes(tb.encode()); (out/'stock.sv').write_bytes(orig[UNIT].encode()); (out/'slot.sv').write_bytes(orig[SLOT].encode()); results={}
    for name,raw in [('candidate',alt),('cross_slot9',D['one'](alt,"next_8 == 4'h1 & vcu_poison_9;","next_8 == 4'h1 & vcu_poison_10;"))]:
        (out/(name+'.sv')).write_bytes(D['one'](raw,'module '+UNIT+'(','module CandidateQueue(').encode()); cmd=[a.iverilog,'-B',a.ivl_dir,'-g2012','-DSYNTHESIS','-s','tb','-o',name+'.vvp','slot.sv','stock.sv',name+'.sv','tb.sv'];
        with (out/(name+'.compile')).open('wb') as f:subprocess.run(cmd,cwd=out,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=300)
        r=subprocess.run([a.vvp,'-M',a.ivl_dir,name+'.vvp'],cwd=out,capture_output=True,text=True,timeout=300);log=r.stdout+r.stderr;(out/(name+'.log')).write_text(log)
        if name=='candidate': D['need'](r.returncode==0 and 'FATAL:' not in log and log.count('QUEUE_COMBINATIONAL_MATCH_300_RESCUES_10_DISPATCH')==1,'no full queue match: '+log[-300:]);results[name]='matched'
        else: D['need'](r.returncode==2 and 'QUEUE_COMBINATIONAL_MATCH_300_RESCUES_10_DISPATCH' not in log and re.search(r'QUEUE_MISMATCH d=\s*8 k=\s*1 miss=1',log),'missing expected negative: '+log[-300:]);results[name]='mismatch detected, destination 8 from slot 9'
    h=lambda b:sha256(b).hexdigest();result=dict(scope='Full SystemVerilog integer queue in four-state simulator with controlled known slot occupancy, grants and operand poisons, natural move control, no clocks. Not sequential or full-CPU equivalence.',candidate_sha256=h(alt.encode()),fixture_sha256=h(tb.encode()),compiler_sha256=h(Path(a.iverilog).read_bytes()),runtime_sha256=h(Path(a.vvp).read_bytes()),resident_pairs=150,rescue_high_low_sequences=300,dispatch_pairs=10,observed_move_and_keep=80,results=results);(out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('FULL_INTEGER_QUEUE_CONTROLLED_MOVE_PAIR_COMPLETE')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--iverilog',required=True);p.add_argument('--vvp',required=True);p.add_argument('--ivl-dir',required=True);run(p.parse_args())
