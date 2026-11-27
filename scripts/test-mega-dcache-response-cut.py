#!/usr/bin/env python3
"""Qualify D-cache response candidates on a source-connected two-lane LSU miss cone."""
import argparse
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
D=runpy.run_path(str(HERE/'test-mega-dcache-forward.py'))
L=runpy.run_path(str(HERE/'test-mega-lsu-miss-fork.py'))
need,once=D['need'],D['once']
DC,LS='dc','ls'; TOP='BoomNonBlockingDCache'; SEAL=D['SEAL']; NAMES={DC:TOP,LS:'LSU'}
FIELDS={'valid':1,'bits_uop_uses_ldq':1,'bits_uop_uses_stq':1,'bits_uop_is_amo':1,'bits_uop_ldq_idx':5,'bits_uop_stq_idx':5}
OUT=[(DC,'io_lsu_resp_0_valid'),(DC,'io_lsu_resp_1_valid'),(LS,'io_core_ld_miss')]
# Lookup ports remain actual indexed reads of shared independent entries. One flat
# input per ordered table is only a Verilog-2005 representation of the packed SV.
TABLE={'_GEN_71':(5,'stq_{}_bits_uop_ldq_idx'),'_GEN_251':(5,'ldq_{}_bits_uop_ldq_idx'),
       '_GEN_309':(2,'ldq_{}_bits_uop_dst_rtype'),'_GEN_166':(1,'stq_{}_bits_data_valid'),
       '_GEN_180':(20,'ldq_{}_bits_uop_br_mask')}


def h(x): return sha256(x).hexdigest()
def width(w): return f'[{w-1}:0] ' if w>1 else ''
@lru_cache(12)
def clean(s): return '\n'.join(line.partition('//')[0].rstrip() for line in s.splitlines())
@lru_cache(4096)
def lhs(src,n):
    q=re.escape(n)
    decl=re.findall(r'^  (?:input|output|reg|wire)\s+(?:\[(\d+):0\]\s+)?'+q+r'(?=\s*[;,=)]|\s*$)',src,re.M)
    need(len(decl)==1,'missing or duplicate declaration '+n); return int(decl[0] or '0')+1

def equation(src,n):
    q=re.findall(r'^  (?:assign |wire\s+(?:\[\d+:0\]\s+)?)'+re.escape(n)+r' = ([^;\n]+);',src,re.M)
    need(len(q)==1,'unexpected equation: '+n); return q[0]

def replace_eq(src,n,expr): return once(src,n+' = '+equation(src,n)+';',n+' = '+expr+';')

def derive(src,split_s2):
    # Qualify each packet with its own branch mask and ldq flag before late
    # arbitration. A killed cache packet still owns the lane; never re-arbitrate.
    ports=['s2_req_0_uop','s2_req_1_uop','_mshrs_io_resp_bits_uop']; new=[]
    for k,p in enumerate(ports):
        new.append(f'  wire vcu_alive_{k} = ~(io_lsu_exception & {p}_uses_ldq) & ((io_lsu_brupdate_b1_mispredict_mask & {p}_br_mask) == 20\'h0);')
    new.append('  wire vcu_replay_ok = _mshrs_io_resp_valid & vcu_alive_2;')
    text=once(src,'  assign io_lsu_resp_0_valid =','\n'.join(new)+'\n  assign io_lsu_resp_0_valid =')
    text=replace_eq(text,'io_lsu_resp_0_valid','cache_resp_0_valid ? vcu_alive_0 : vcu_replay_ok')
    text=replace_eq(text,'io_lsu_resp_1_valid','cache_resp_1_valid ? vcu_alive_1 : (cache_resp_0_valid & vcu_replay_ok)')
    if split_s2:
        for i in (0,1):
            s='' if i==0 else '_1'; hit=f's2_hit_{i}'; cmd=f's2_req_{i}_uop_mem_cmd'
            hit_ok=f'{hit} & ~((s2_nack_hit_{i} | s2_nack_victim_{i} | s2_nack_wb_{i}) & (|s2_type))'
            miss_ok=f"_mshrs_io_req_{i}_ready & mshrs_io_req_{i}_valid & (({cmd} == 5'h1) | ({cmd} == 5'h11))"
            text=replace_eq(text,f'cache_resp_{i}_valid',f's2_valid_REG{s} & s2_send_resp_REG{s} & (({hit_ok}) | ({miss_ok}))')
    return text


def kit_sources(kit):
    manifest=(kit/'CANDIDATE.sha256').read_bytes(); need(h(manifest)==SEAL,'not the recovery kit')
    src={}; ids={}
    for k,n in {**NAMES,'tile':'BoomTile'}.items():
        raw=(kit/'rtl'/(n+'.sv')).read_bytes(); d=h(raw); need(f'{d}  rtl/{n}.sv'.encode() in manifest.splitlines(),'wrong parent '+n)
        ids[n]=d; src[k]=raw.decode()
    need(ids[TOP]==D['LEAF'] and ids['LSU']==L['LSU'],'different parents'); return src,ids


def verify_links(src):
    tile=clean(src['tile']); pins={}; dc=clean(src[DC]); ls=clean(src[LS])
    for k,inst in [(DC,'dcache'),(LS,'lsu')]:
        blocks=re.findall(r'^  '+NAMES[k]+' '+inst+r' \((.*?)^  \);',tile,re.S|re.M); need(len(blocks)==1,'wrong instance '+inst)
        pins[k]=dict(re.findall(r'^    \.(\w+)\s+\((\w+)\)',blocks[0],re.M))
    for i in (0,1):
        for field,w in FIELDS.items():
            d=f'io_lsu_resp_{i}_{field}'; l=f'io_dmem_resp_{i}_{field}'
            need(pins[DC][d]==pins[LS][l]=='_dcache_'+d and lhs(dc,d)==lhs(ls,l)==w,'cross-lane or width error '+d)
    need(pins[DC]['io_lsu_brupdate_b1_mispredict_mask']==pins[LS]['io_dmem_brupdate_b1_mispredict_mask'] and
         equation(ls,'io_dmem_brupdate_b1_mispredict_mask')=='io_core_brupdate_b1_mispredict_mask','mask not shared')


def boundaries():
    b={DC:{'io_lsu_exception':1,'io_lsu_brupdate_b1_mispredict_mask':20,'s2_type':3,'_mshrs_io_resp_valid':1},
       LS:{'io_core_ld_miss_REG':1}}
    for i in (0,1):
        suf='' if not i else '_1'
        for n in (f's2_valid_REG{suf}',f's2_send_resp_REG{suf}',f's2_hit_{i}',f's2_nack_hit_{i}',f's2_wb_idx_matches_{i}',f'_mshrs_io_secondary_miss_{i}',f'_mshrs_io_req_{i}_ready'): b[DC][n]=1
        b[DC][f's2_req_{i}_uop_mem_cmd']=5
        for p in (f's2_req_{i}_uop','_mshrs_io_resp_bits_uop'):
            for n,w in dict(br_mask=20,ldq_idx=5,stq_idx=5,uses_ldq=1,uses_stq=1,is_amo=1).items(): b[DC][p+'_'+n]=w
        for n,w in {f'wb_forward_valid_{i}':1,f'wb_forward_ldq_idx_{i}':5,f'wb_forward_stq_idx_{i}':5, ('spec_ld_succeed_REG' if not i else 'spec_ld_succeed_REG_2'):1,'spec_ld_succeed_REG_'+str(i*2+1):5}.items(): b[LS][n]=w
    return b


def extract(src,unused=()):
    src={k:clean(src[k]) for k in NAMES}; b=boundaries(); ports={}; body=[]; intern={}; active=set()
    literal=r"\d+'[bodhBODH][0-9A-Fa-f_xXzZ]+"; token=re.compile(literal+r'|\b[A-Za-z_]\w*\b')
    def net(k,n):
        key=(k,n); name=k+'_'+n
        if key in intern: return intern[key]
        need(key not in active,'combinational loop '+name); active.add(key)
        if n in b[k]:
            w=b[k][n]; need(lhs(src[k],n)==w,'wrong cut width '+n); ports[name]=w
        elif k==LS and n in TABLE:
            w,template=TABLE[n]; elems=[template.format(i) for i in reversed(range(32))]
            expected='{' + ', '.join('{'+v+'}' for v in elems) + '}'; need(re.search(r'^  wire\s+'+re.escape('[31:0]'+(f'[{w-1}:0]' if w>1 else ''))+r'\s+'+n+' = '+re.escape(expected)+';',src[k],re.M),'wrong table order '+n)
            need(all(lhs(src[k],s)==w for s in elems),'wrong table entry width'); flat=name+'_flat'; ports[flat]=32*w
            body.append('wire '+width(w)+name+' [0:31];'); body.extend(f'assign {name}[{i}] = {flat}[{i*w} +: {w}];' for i in range(32))
        elif k==LS and n.startswith('io_dmem_resp_'):
            name=net(DC,n.replace('io_dmem_resp_','io_lsu_resp_'))
        elif k==LS and n=='io_core_brupdate_b1_mispredict_mask': name=net(DC,'io_lsu_brupdate_b1_mispredict_mask')
        else:
            w=lhs(src[k],n); expr=equation(src[k],n); expr=token.sub(lambda m:m[0] if "'" in m[0] else net(k,m[0]),expr); body.append('wire '+width(w)+name+' = '+expr+';')
        active.remove(key); intern[key]=name; return name
    nets=[net(k,n) for k,n in OUT]; expected={k+'_'+n for k in b for n in b[k]}|{'ls_'+n+'_flat' for n in TABLE}
    missing=expected-set(ports); need(missing==set(unused) and not set(ports)-expected,'boundary drift '+str(sorted(missing)))
    for k in b:
        for n in b[k]:
            if k+'_'+n in missing: net(k,n)  # retain identical SAT pins for intentionally disconnected controls
    return 'module top('+', '.join('input '+width(w)+n for n,w in sorted(ports.items()))+', output [2:0] o);\n'+'\n'.join(body)+'\nassign o = {'+', '.join(reversed(nets))+'};\nendmodule\n',ports


def measure(mod,ports):
    roots=set(); p=mod['ports']; drivers={}; types=Counter()
    for n,w in ports.items():
        need(len(p[n]['bits'])==w and p[n]['direction']=='input','mapped port '+n); roots.update(p[n]['bits'])
    need(len(roots)==sum(ports.values()) and p['o']['direction']=='output' and len(p['o']['bits'])==3,'interface alias')
    for c in mod['cells'].values():
        kind=c['type']; need(re.fullmatch(r'LUT[1-6]|MUXF[789]|INV|MUXCY|XORCY',kind),'unexpected primitive '+kind)
        inp=[];out=[]
        for pin,bs in c['connections'].items(): (inp if c['port_directions'][pin]=='input' else out).extend(bs)
        need(len(out)==1 and out[0] not in drivers,'primitive output'); drivers[out[0]]=inp;types[kind]+=1
    groups={'all':roots,'branch_mask':set(p['dc_io_lsu_brupdate_b1_mispredict_mask']['bits'])}
    for i in (0,1):
        for n,key in [('mshr_ready',f'dc__mshrs_io_req_{i}_ready'),('s2_hit',f'dc_s2_hit_{i}'),('op',f'dc_s2_req_{i}_uop_mem_cmd')]: groups[f'{n}_{i}']=set(p[key]['bits'])
    groups['queue_data']=set(v for k,pp in p.items() if k.endswith('_flat') for v in pp['bits'])
    depths={}
    for label,starts in groups.items():
        @lru_cache(None)
        def depth(bit):
            if bit in starts: return 0
            if bit in roots or bit in ('0','1'): return -10000
            need(bit in drivers,'orphan driver'); return 1+max(map(depth,drivers[bit]))
        depths[label]=[d if d>=0 else None for d in map(depth,p['o']['bits'])]
    return dict(cells=dict(sorted(types.items())),primitive_depth=depths)


def proof(out,y,label,gold,gate,equal):
    script=(f'read_verilog -noautowire {gold}.v; rename top gold; '
            f'read_verilog -noautowire {gate}.v; rename top gate; proc; memory; opt; '
            'miter -equiv -make_outputs -flatten gold gate cmp; hierarchy -check -top cmp; '
            'opt; check -assert; sat -prove trigger 0 -show gold_o -show gate_o cmp')
    log=L['cmd'](out,y,'proof_'+label,script)
    need(log.count('SAT proof finished - no model found: SUCCESS!')==int(equal) and
         log.count('SAT proof finished - model found: FAIL!')==int(not equal),'unexpected SAT result '+label)
    if equal: return {'status':'equivalent'}
    bits={}
    for n in ('gold_o','gate_o'):
        m=re.findall(r'^\s+\\'+n+r'\s+\d+\s+[0-9a-fA-F]+\s+([01]{3})\s*$',log,re.M)
        need(len(m)==1,'missing binary witness '+label+' '+n); bits[n]=m[0]
    need(bits['gold_o']!=bits['gate_o'],'unchanged witness'); return {'status':'counterexample','output_bits_msb_first':bits}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('kit','yosys','out'): ap.add_argument(n,type=Path)
    a=ap.parse_args(); kit=a.kit.resolve(strict=True); y=a.yosys.resolve(strict=True); out=a.out.resolve(); need(not a.out.is_symlink() and not out.exists() and kit not in out.parents and out not in kit.parents,'need fresh external output'); src,ids=kit_sources(kit); verify_links(src);out.mkdir(mode=0o700)
    variants={'stock':src[DC],'source_first':derive(src[DC],False),'source_and_s2':derive(src[DC],True)}; alt=variants['source_and_s2']
    tag='io_lsu_resp_1_bits_uop_ldq_idx'; tg=equation(alt,tag); need(tg.endswith(' : s2_req_1_uop_ldq_idx'),'wrong lane tag site')
    controls={'wrong_local_ldq_tag':replace_eq(alt,tag,once(tg,' : s2_req_1_uop_ldq_idx',' : s2_req_0_uop_ldq_idx')),
              'wrong_lane_mask':once(alt,'cache_resp_1_valid ? vcu_alive_1 :','cache_resp_1_valid ? vcu_alive_0 :'),
              'suppress_replay_on_killed_cache0':once(alt,'(cache_resp_0_valid & vcu_replay_ok)','((cache_resp_0_valid & vcu_alive_0) & vcu_replay_ok)'),
              'drop_store17':once(alt,"((s2_req_1_uop_mem_cmd == 5'h1) | (s2_req_1_uop_mem_cmd == 5'h11))","(s2_req_1_uop_mem_cmd == 5'h1)")}
    abc=shutil.which('berkeley-abc'); need(abc,'missing mapper'); yv=subprocess.check_output([y,'-V'],text=True).strip(); av=subprocess.check_output([abc,'-c','version'],text=True).strip().splitlines()[-1]
    sat={}; maps={}; cuts={}; inputs=None
    for label,parent in {**variants,**controls}.items():
        unused={'wrong_local_ldq_tag':['dc_s2_req_1_uop_ldq_idx']}.get(label,())
        cut,p=extract({**src,DC:parent},unused); need(inputs is None or p==inputs,'changed interface'); inputs=p; raw=cut.encode(); (out/(label+'.v')).write_bytes(raw); cuts[label]=h(raw)
        if label in variants and label!='stock': (out/(label+'-'+TOP+'.sv')).write_bytes(parent.encode())
        if label!='stock':
            sat[label]=proof(out,y,label,'stock',label,label in variants)
        if label in ('stock','wrong_local_ldq_tag'):
            valid_only=once(cut,'assign o = {ls_io_core_ld_miss,',"assign o = {1'b0,")
            (out/(label+'_valid_only.v')).write_bytes(valid_only.encode())
        if label=='wrong_local_ldq_tag':
            sat['wrong_local_ldq_tag_valid_only']=proof(out,y,label+'_valid_only','stock_valid_only',label+'_valid_only',True)
            witness=sat[label]['output_bits_msb_first']; need(witness['gold_o'][1:]==witness['gate_o'][1:] and witness['gold_o'][0]!=witness['gate_o'][0],'not a downstream-only mismatch')
        if label in variants:
            log=L['cmd'](out,y,'map_'+label,'read_verilog -noautowire '+label+'.v; synth_xilinx -family xcup -flatten -top top; check -assert; write_json '+label+'.json'); need(log.count('Running ABC command: berkeley-abc -s -f')==1,'unexpected mapper');maps[label]=measure(json.loads((out/(label+'.json')).read_bytes())['modules']['top'],p)
    result=dict(scope='Same-cycle two-state D-cache/LSU cut. Two valid outputs plus actual LSU speculative miss with five ordered queue tables. XCUP primitive mapping, not delay or board performance.',kit_sha256=SEAL,parents_sha256=ids,candidates_sha256={n:h(v.encode()) for n,v in variants.items() if n!='stock'},cuts_sha256=cuts,inputs_bits=sum(inputs.values()),ordered_tables={n:[32,w] for n,(w,_) in TABLE.items()},response_signals_verified_across_tile=12,outputs_in_order=[n for _,n in OUT],tools={'yosys':yv,'abc':av,'yosys_sha256':h(y.read_bytes()),'abc_sha256':h(Path(abc).read_bytes())},sat=sat,mapping=maps)
    (out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps(result,indent=2))

if __name__=='__main__': main()
