#!/usr/bin/env python3
"""Exercise the complete stock and candidate FetchBuffer modules with identical inputs."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess

P = runpy.run_path(str(Path(__file__).with_name('prove-mega-fetch-prefix.py')))
need = P['need']


def testbench(src):
    ports = re.findall(r'^  (input|output)\s+(?:\[(\d+):0\]\s+)?(\w+),?\s*//',src,re.M)
    ports = [(d,int(w or 0)+1,n) for d,w,n in ports]
    ins = [(w,n) for d,w,n in ports if d=='input']; outs = [n for d,w,n in ports if d=='output']
    need(len(set(n for d,w,n in ports))==117 and len(ins)==55 and sum(w for w,n in ins)==605 and
         sum(w for d,w,n in ports if d=='output')==510, 'unexpected real module interface')
    text = ['module tb;','integer t,seed,stalls,wraps,pops,live; reg [255:0] masks; reg [31:0] tails,oldtail; reg advancing;']
    text += [f'reg [{w-1}:0] {n};' for w,n in ins]
    pins=', '.join(f'.{n}({n})' for w,n in ins); text += ['FetchBuffer g('+pins+');','Candidate c('+pins+');']
    obs=outs+['tail','head','maybe_full']+[f'fb_uop_ram_{j}_inst' for j in range(32)]
    read=lambda a: '{'+','.join(a+'.'+n for n in obs)+'}'
    text+=['task compare; begin',f'if ({read("g")} !== {read("c")}) begin $display("FETCH_LOCKSTEP_MISMATCH %0d",t); $finish_and_return(2); end','end endtask',
           "initial begin seed=32'h51a7d02; clock=0; tails=0; masks=0; stalls=0; wraps=0; pops=0; live=0;",
           'for (t=0;t<2624;t=t+1) begin']
    text += [f'{n}={{$random(seed),$random(seed)}};' for w,n in ins if n!='clock']
    text += ['''reset=(t==0); io_clear=0;
if(t<512) begin io_enq_valid=t[0]; io_enq_bits_mask=t/2; io_clear=!t[0]; io_deq_ready=0; end
else if(t<546) begin io_enq_valid=1; io_enq_bits_mask=8'hff; io_deq_ready=0; end
else if(t<576) begin io_enq_valid=0; io_deq_ready=1; end
else begin reset=(t%337==0); io_clear=(t%113==0); end
#2;
if(t>0) compare;
if(io_enq_valid && g.io_enq_ready && !reset && !io_clear) masks[io_enq_bits_mask]=1;
if(io_enq_valid && !g.io_enq_ready && !reset && !io_clear) stalls=stalls+1;
if(g.io_deq_valid && io_deq_ready && !reset && !io_clear) pops=pops+1;
oldtail=g.tail; advancing=(g.io_enq_ready && io_enq_valid && !reset && !io_clear);
clock=1; #2; compare; tails=tails|g.tail;
if ((^g.tail === 1'bx) || g.tail==0 || (g.tail & (g.tail-1))!=0) $fatal(1,"BAD_TAIL");
if(advancing && g.tail<oldtail) wraps=wraps+1;''']
    for j in range(4):
        text += [f"if(g.io_deq_valid && g.io_deq_bits_uops_{j}_valid) begin if (^g.io_deq_bits_uops_{j}_bits_inst === 1'bx) $fatal(1,\"UNKNOWN_LIVE_INSTRUCTION\"); live=live+1; end"]
    text += ['clock=0; #1; end',"if(masks!=={256{1'b1}} || tails!==32'hffffffff || stalls<10 || wraps<8 || pops<50 || live<200) $fatal(1,\"INCOMPLETE_COVERAGE\");"]
    for j in range(32):
        text += [f"if (^g.fb_uop_ram_{j}_inst === 1'bx) $fatal(1,\"UNKNOWN_SLOT\");"]
    text += ['$display("FETCH_LOCKSTEP_OK cycles=2624 masks=256 tails=32 stalls=%0d wraps=%0d pops=%0d valid_lane_samples=%0d",stalls,wraps,pops,live); $finish; end endmodule']
    return '\n'.join(text)+'\n'


def run(kit,out,ivl,vvp,ivldir):
    raw=(kit/'rtl/FetchBuffer.sv').read_bytes(); seal=(kit/'CANDIDATE.sha256').read_bytes(); digest=lambda x:sha256(x).hexdigest()
    need(digest(raw)==P['UNIT'] and digest(seal)==P['KIT'] and (P['UNIT']+'  rtl/FetchBuffer.sv').encode() in seal.splitlines(), 'different physical source')
    src=raw.decode(); alt=P['masked'](src); local=P['masked'](src,local_select=True)
    bad=alt.replace('({32{_GEN_240}} & io_enq_bits_exp_insts_7)','({32{_GEN_240}} & io_enq_bits_exp_insts_6)',1);need(bad!=alt,'wrong-lane mutation absent')
    tb=testbench(src);out.mkdir(mode=0o700); (out/'gold.sv').write_bytes(raw);(out/'tb.sv').write_bytes(tb.encode());records={}
    for name,unit in [('onehot',alt),('onehot_local',local),('wrong_lane',bad)]:
        d=out/name;d.mkdir();need(unit.count('module FetchBuffer(')==1,'ambiguous top');(d/'candidate.sv').write_bytes(unit.replace('module FetchBuffer(','module Candidate(').encode())
        subprocess.run([str(ivl),'-B',str(ivldir),'-g2012','-s','tb','-o','sim','../gold.sv','candidate.sv','../tb.sv'],cwd=d,check=True,timeout=90)
        proc=subprocess.run([str(vvp),'-M',str(ivldir),'sim'],cwd=d,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90);(d/'sim.log').write_text(proc.stdout)
        if name=='wrong_lane':
            m=re.findall(r'FETCH_LOCKSTEP_MISMATCH (\d+)',proc.stdout);need(proc.returncode==2 and len(m)==1 and 'FETCH_LOCKSTEP_OK' not in proc.stdout,'wrong lane not detected'); r={'detected_at_cycle':int(m[0])}
        else:
            lines=re.findall(r'^FETCH_LOCKSTEP_OK cycles=2624 masks=256 tails=32 stalls=(\d+) wraps=(\d+) pops=(\d+) valid_lane_samples=(\d+)$',proc.stdout,re.M)
            need(proc.returncode==0 and len(lines)==1 and 'FATAL:' not in proc.stdout,'lockstep or coverage failed: '+proc.stdout[-300:]);r=dict(zip(('stalled_enqueue_cycles','nonclear_tail_wraps','dequeue_handshakes','valid_lane_samples'),map(int,lines[0])))
        records[name]=dict(candidate_module_sha256=digest(unit.encode()),**r)
    tools={p.name:digest(p.read_bytes()) for p in (ivl,vvp,ivldir/'ivl',ivldir/'ivlpp',ivldir/'vvp.tgt')}
    result=dict(scope='Finite complete-module four-state differential simulation, not formal whole-module equivalence or a CoreMark run.',source_sha256=P['UNIT'],testbench_sha256=digest(tb.encode()),tool_sha256=tools,clocks=2624,input_bits=605,output_bits=510,all_accepted_masks=256,all_tail_positions=32,profiles=records)
    (out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path)
    for k in ('iverilog','vvp','ivl-dir'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();run(a.kit.resolve(),a.out.resolve(),a.iverilog.resolve(),a.vvp.resolve(),a.ivl_dir.resolve())
