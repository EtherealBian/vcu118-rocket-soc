#!/usr/bin/env python3
"""Derive and prove a late-response-select LSU miss candidate without touching its sealed kit."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess

SEAL='ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456'
LSU='5749f211d5093a7ef4ac6bba75706d2a4ab3a016b2fb814da34fd7bed44d80d7'

def need(x,m):
    if not x: raise ValueError(m)

def h(p): return sha256(p.read_bytes()).hexdigest()

def rhs(text,n):
    hits=re.findall(r'^  (?:wire\s+(?:\[[\d:]+\]\s+)?|assign )'+re.escape(n)+r' = ([^;\n]+);',text,re.M)
    need(len(hits)==1,'wrong source count '+n); return hits[0]

def lane(i):
    base=1759 if i==0 else 1810; p='io_dmem_resp_%d_'%i; suffix='' if not i else '_1'
    return dict(valid=p+'valid',use=p+'bits_uop_uses_ldq',st=p+'bits_uop_uses_stq',amo=p+'bits_uop_is_amo',
                atomic='_GEN_%d'%base,fired='dmem_resp_fired_'+str(i),both='_GEN_%d'%(base+1),only='_GEN_%d'%(base+2),
                select='_GEN_%d'%(base+14),iresp='io_core_exe_%d_iresp_valid_0'%i,forward='wb_forward_valid_'+str(i),
                itype='_GEN_%d'%(base+9),stdata='_GEN_%d'%(base+10),live='live'+suffix,send='send_iresp'+suffix,
                ldtag='_GEN_251['+p+'bits_uop_ldq_idx]',sttag='_GEN_71['+p+'bits_uop_stq_idx]',
                fwtag='_GEN_251[wb_forward_ldq_idx_%d]'%i,expected='spec_ld_succeed_REG_'+str(2*i+1),
                pending='spec_ld_succeed_REG'+('' if not i else '_2'))

def derive(src):
    extra=[]; fails=[]
    for i in (0,1):
        p=lane(i); f='vcu_fw_success_'+str(i); ret='vcu_response_success_'+str(i); take='vcu_consumes_response_'+str(i); bad='vcu_lane_miss_'+str(i)
        extra += ['  wire '+f+' = '+('{forward} & ({itype} == 2\'h0) & {stdata} & {live} & ({fwtag} == {expected});').format(**p),
                  '  wire '+ret+' = '+('{use} ? ({send} & ({ldtag} == {expected})) : ({atomic} & ({sttag} == {expected}));').format(**p),
                  '  wire '+take+' = '+('{use} | {atomic};').format(**p),
                  f"  wire {bad} = {p['valid']} ? ({p['pending']} & ~({ret} | (~{take} & {f}))) : ({p['pending']} & ~{f});"]
        fails.append(bad)
    old='  assign io_core_ld_miss = '+rhs(src,'io_core_ld_miss')+';'
    need('vcu_fw_success_' not in src and src.count(old)==1,'unexpected parent'); return src.replace(old,'\n'.join(extra+['  assign io_core_ld_miss = io_core_ld_miss_REG & ('+' | '.join(fails)+');']))

def cut(src,alt):
    ports={'io_core_ld_miss_REG':1}; eq=[]; subs={}
    for i in (0,1):
        p=lane(i)
        for k in ('valid','use','st','amo','forward','itype','stdata','live','send','expected','pending'):
            ports[p[k]]={'itype':2,'expected':5}.get(k,1)
        for k in ('ldtag','sttag','fwtag'):
            n=k+str(i); ports[n]=5; subs[p[k]]=n
        names=[p['atomic']]+(['vcu_'+k+'_'+str(i) for k in ('fw_success','response_success','consumes_response','lane_miss')] if alt else
                               [p[k] for k in ('fired','both','only','select','iresp')])
        eq+=['wire '+n+' = '+rhs(src,n)+';' for n in names]
    eq+=['assign io_core_ld_miss = '+rhs(src,'io_core_ld_miss')+';']; body='\n'.join(eq)
    for a,b in subs.items(): need(a in body,'missing indexed operand'); body=body.replace(a,b)
    return 'module cone('+', '.join('input '+(f'[{w-1}:0] ' if w!=1 else '')+n for n,w in ports.items())+', output io_core_ld_miss);\n'+body+'\nendmodule\n',ports

def cmd(out,y,name,script):
    (out/(name+'.ys')).write_text(script+'\n'); proc=subprocess.run([y,'-s',name+'.ys'],cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
    (out/(name+'.log')).write_bytes(proc.stdout); need(proc.returncode==0,name+' failed'); return proc.stdout.decode(errors='replace')

def lutmap(folder,y,name):
    log=cmd(folder,y,'map_'+name,f'read_verilog -noautowire {name}.v; hierarchy -check -top cone; synth -top cone -noabc; abc -lut 6; clean; check -assert; write_json {name}.json')
    need(re.findall(r'^Running ABC command: (\S+) -s -f .*?abc\.script 2>&1$',log,re.M)==['berkeley-abc'],'unexpected mapper invocation')
    mod=json.loads((folder/(name+'.json')).read_bytes())['modules']['cone']; ports=mod['ports']; prod={}
    for c in mod['cells'].values():
        need(c['type']=='$lut' and len(c['connections']['Y'])==1 and len(c['connections']['A'])<=6,'unexpected mapped cell'); prod[c['connections']['Y'][0]]=c['connections']['A']
    def depth(bit,roots,memo):
        if bit not in memo:
            if bit not in prod: memo[bit]=0 if bit in roots else -1000
            else: memo[bit]=1+max(depth(b,roots,memo) for b in prod[bit])
        return memo[bit]
    o=ports['io_core_ld_miss']['bits'][0]; ds={n:depth(o,set(p['bits']),{}) for n,p in ports.items() if p['direction']=='input'}
    need(min(ds.values())>0,'unconnected boundary control'); return dict(luts=len(prod),max_depth=max(ds.values()),input_depth=ds)

def main():
    a=argparse.ArgumentParser(description=__doc__); a.add_argument('kit',type=Path); a.add_argument('yosys',type=Path); a.add_argument('out',type=Path); a=a.parse_args()
    kit=a.kit.resolve(strict=True); y=a.yosys.resolve(strict=True); out=a.out.resolve(); need(not a.out.is_symlink() and not out.exists() and kit not in out.parents,'fresh external output required'); src=kit/'rtl/LSU.sv'
    need(h(kit/'CANDIDATE.sha256')==SEAL and h(src)==LSU,'wrong kit or parent'); out.mkdir(mode=0o700); orig=src.read_bytes().decode(); alt=derive(orig); (out/'LSU.sv').write_bytes(alt.encode())
    g,ports=cut(orig,False); q,p=cut(alt,True); need(p==ports,'mismatched inputs')
    def change(text,a,b): need(text.count(a)==1,'targeted control missing'); return text.replace(a,b)
    cases={'stock':g,'candidate':q,'no_priority':change(q,'~vcu_consumes_response_0 & vcu_fw_success_0','vcu_fw_success_0'),
           'wrong_forward_tag':change(q,'fwtag1 == spec_ld_succeed_REG_3','fwtag1 == spec_ld_succeed_REG_1'),
           'no_store_response':change(q,'_GEN_1810 & (sttag1',"1'b0 & (sttag1")}
    sat={}
    for label,text in cases.items():
        (out/(label+'.v')).write_text(text)
        if label=='stock': continue
        log=cmd(out,y,'proof_'+label,'read_verilog -noautowire stock.v; rename cone gold; read_verilog -noautowire '+label+'.v; rename cone gate; miter -equiv -flatten gold gate cmp; hierarchy -check -top cmp; proc; opt; check -assert; sat -prove trigger 0 cmp'); ok=label=='candidate'
        need(log.count('SAT proof finished - no model found: SUCCESS!')==int(ok) and log.count('SAT proof finished - model found: FAIL!')==int(not ok),'unexpected SAT decision'); sat[label]='equivalent' if ok else 'counterexample'
    abc=shutil.which('berkeley-abc'); need(abc,'missing mapper on PATH')
    av=subprocess.check_output([abc,'-c','version'],text=True).strip().splitlines()[-1]; yv=subprocess.check_output([y,'-V'],text=True).strip()
    need(av.startswith('UC Berkeley, ABC ') and yv.startswith('Yosys '),'missing tool version')
    result=dict(scope='Actual dual-lane LSU miss equations cut after queue reads; arbitrary two-state inputs. Generic 6-LUT mapping, no placement, timing or board score.',
                kit_sha256=SEAL,stock_parent_sha256=LSU,candidate_parent_sha256=h(out/'LSU.sv'),cut_bits=sum(ports.values()),yosys_sha256=h(y),yosys_version=yv,abc_sha256=h(Path(abc)),abc_version=av,sat=sat,
                cut_sha256={n:h(out/(n+'.v')) for n in ('stock','candidate')},mapping={n:lutmap(out,y,n) for n in ('stock','candidate')})
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))

if __name__=='__main__': main()
