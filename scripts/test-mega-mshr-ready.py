#!/usr/bin/env python3
"""Move two-lane MSHR request arbitration late; compare the actual recovery RTL cones."""
import argparse
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import shutil

HERE=Path(__file__).resolve().parent
D=runpy.run_path(str(HERE/'test-mega-dcache-response-cut.py'))
need,once,eq,replace,width,clean,lhs=[D[k] for k in ('need','once','equation','replace_eq','width','clean','lhs')]
H=lambda b:sha256(b).hexdigest()
P,C,Q='BoomMSHRFile','BoomMSHR','BranchKillableQueue'
CODES=(1,17,7,4,9,10,11,8,12,13,14,15,3,6)


def load(kit):
    manifest=(kit/'CANDIDATE.sha256').read_bytes(); need(H(manifest)==D['SEAL'],'wrong board candidate')
    result={}
    for name in (P,C,Q,'BoomNonBlockingDCache'):
        raw=(kit/'rtl'/(name+'.sv')).read_bytes(); need(f'{H(raw)}  rtl/{name}.sv'.encode() in manifest.splitlines(),'changed '+name); result[name]=raw.decode()
    dc=pins(clean(result['BoomNonBlockingDCache']),P,'mshrs'); q=pins(clean(result[C]),Q,'rpq')
    for i in (0,1):
        for field in ('valid','ready'):
            n=f'io_req_{i}_{field}'; need(dc[n]==('_' if field=='ready' else '')+'mshrs_'+n,'changed D-cache link')
    qs=clean(result[Q]); need(q['io_enq_ready']=='_rpq_io_enq_ready' and eq(qs,'io_enq_ready')=='~full' and
        eq(qs,'full')=='ptr_match & maybe_full' and eq(qs,'ptr_match')=='enq_ptr_value == deq_ptr_value','queue ready boundary changed')
    return result


def pins(src,mod,name):
    block=re.findall(r'^  '+mod+' '+name+r' \((.*?)^  \);',src,re.M|re.S); need(len(block)==1,'wrong instance '+name)
    pairs=re.findall(r'^    \.(\w+)\s+\((\w+)\)',block[0],re.M); d=dict(pairs); need(len(d)==len(pairs),'duplicate simple port'); return d


def derive(p,c,classes):
    # Do not change the child state machine or the selected secondary valid it consumes.
    # Its two extra outputs are the same ready function at two constant request classes.
    s=clean(c); expr=eq(s,'io_req_sec_rdy_0'); m=re.fullmatch(r'~\(\(([^()]*)\) & ~\(([^()]*)\)\) & (.+)',expr)
    need(m and [eq(s,n) for n in m[1].split(' | ')]==[f"io_req_uop_mem_cmd == 5'h{v:X}" for v in CODES] and
         [eq(s,n) for n in m[2].split(' | ')]==[f"req_uop_mem_cmd == 5'h{v:X}" for v in CODES],'different acquisition decoder')
    if classes:
        c=once(c,'  output         io_req_sec_rdy,','  output         vcu_open,\n  output         vcu_permitted,\n  output         io_req_sec_rdy,')
        c=once(c,'  assign io_req_sec_rdy =',f'  assign vcu_open = {m[3]};\n  assign vcu_permitted = vcu_open & ({m[2]});\n  assign io_req_sec_rdy =')
        for j in range(8):
            key=f'  wire         _mshrs_{j}_io_req_sec_rdy;'; p=once(p,key,''.join(f'  wire         vcu_{n}_{j};\n' for n in ('open','permitted'))+key)
            key=f'    .io_req_sec_rdy                     (_mshrs_{j}_io_req_sec_rdy),'; p=once(p,key,''.join(f'    .vcu_{n} (vcu_{n}_{j}),\n' for n in ('open','permitted'))+key)
    cache=eq(clean(p),'cacheable'); need('mshrs_7_io_req_addr' in cache,'cacheability decode')
    for i in (0,1):
        lane=f'io_req_{i}'; idx=f'idx_matches_{i}_'; dec=cache.replace('mshrs_7_io_req_addr',lane+'_bits_addr')
        def any_ready(root): return '('+' | '.join(f'({idx}{j} & '+root.format(j)+' )' for j in range(8))+')'
        if classes:
            classifier='('+' | '.join(f"({lane}_bits_uop_mem_cmd == 5'h{v:X})" for v in CODES)+')'
            sec='('+classifier+' ? '+any_ready('vcu_permitted_{}')+' : '+any_ready('vcu_open_{}')+')'
        else: sec=any_ready('_mshrs_{}_io_req_sec_rdy')
        eligible=f'({lane}_valid & tag_match_{i} & {sec})'; grant='io_req_1_valid' if i else '~io_req_1_valid'
        p=replace(p,lane+'_ready_0',f'{grant} & (({dec}) ? sdq_rdy & (idx_match_{i} ? {eligible} : pri_rdy) : _mmios_0_io_req_ready)')
    return p,c


def extract(p,c,queue=None):
    p,c=clean(p),clean(c); links=[pins(p,C,'mshrs_'+str(j)) for j in range(8)]
    inputs={'io_req_0_valid':1,'io_req_1_valid':1,'sdq_val':17,'mshr_alloc_idx_REG':3,'_mmios_0_io_req_ready':1,'io_req_is_probe_0':1}
    for i in (0,1): inputs.update({f'io_req_{i}_bits_addr':40,f'io_req_{i}_bits_uop_mem_cmd':5})
    reverse={}; local={'state':5,'req_uop_mem_cmd':5,'_rpq_io_enq_ready':1}
    qr={'enq_ptr_value':4,'deq_ptr_value':4,'maybe_full':1}
    if queue is not None:
        queue=clean(queue); local.update(req_addr=40,req_way_en=8); del local['_rpq_io_enq_ready']
        for i in (0,1): inputs[f'io_req_{i}_bits_way_en']=8
    for j,ln in enumerate(links):
        need(ln['io_req_is_probe']=='io_req_is_probe_0' and ln['io_req_uop_mem_cmd']=='mshrs_7_io_req_uop_mem_cmd','not the shared probe/selected command')
        for n,w in (('io_idx_valid',1),('io_tag_valid',1),('io_idx_bits',6),('io_tag_bits',28)):
            pp=ln[n]; need(pp==f'_mshrs_{j}_{n}' and lhs(c,n)==w,'MSHR address table pin')
            if queue is None: inputs[pp]=w
            else: reverse[pp]=(j,n)
        if queue is not None:
            for n,w in (('io_way_valid',1),('io_way_bits',8)):
                pp=ln[n]; need(pp==f'_mshrs_{j}_{n}' and lhs(c,n)==w,'way pin'); reverse[pp]=(j,n)
        for n in ['io_req_pri_rdy','io_req_sec_rdy']+(['vcu_open','vcu_permitted'] if 'vcu_open' in ln else []):
            need(lhs(c,n)==lhs(p,ln[n])==1,'ready pin width'); reverse[ln[n]]=(j,n)
    ports={}; lines=[]; visiting=set(); token=re.compile(r"\d+'[bdhoBDHO][0-9A-Fa-f_xXzZ]+|\b[A-Za-z_]\w*\b")
    @lru_cache(None)
    def net(j,n):
        src=p if j<0 else c if j<8 else queue; name=n if j<0 else f'm{j}_{n}' if j<8 else f'q{j-8}_{n}'
        if 0<=j<8 and queue is not None and n=='_rpq_io_enq_ready': return net(j+8,'io_enq_ready')
        if j<0 and n in reverse: return net(*reverse[n])
        if j>=0 and n in ('io_req_is_probe','io_req_uop_mem_cmd'): return net(-1,links[j][n])
        w=lhs(src,n); cut=inputs if j<0 else local if j<8 else qr
        if n in cut:
            need(w==cut[n],'width drift '+n); ports[name]=w
        else:
            need((j,n) not in visiting,'combinational loop'); visiting.add((j,n))
            expr=token.sub(lambda x:x[0] if "'" in x[0] else net(j,x[0]),eq(src,n)); visiting.remove((j,n))
            lines.append('wire '+width(w)+name+' = '+expr+';')
        return name
    outs=[net(-1,f'io_req_{i}_ready') for i in (1,0)]
    if queue is not None: outs=[net(-1,f'io_secondary_miss_{i}') for i in (1,0)]+outs
    expected={**inputs,**{f'm{j}_{n}':w for j in range(8) for n,w in local.items()}}
    if queue is not None: expected.update({f'q{j}_{n}':w for j in range(8) for n,w in qr.items()})
    need(ports==expected,'boundary mismatch: '+str(ports.keys()^expected.keys()))
    return 'module top('+', '.join('input '+width(w)+n for n,w in sorted(ports.items()))+f', output [{len(outs)-1}:0] o);\n'+'\n'.join(lines)+'\nassign o={'+', '.join(outs)+'};\nendmodule\n',ports


def mapping(mod,ports):
    pins=mod['ports']; need(set(pins)==set(ports)|{'o'} and len(pins['o']['bits'])==2,'mapping interface')
    select=lambda group:{b for n,w in ports.items() if group(n) for b in pins[n]['bits']}
    roots=select(lambda n:True); need(len(roots)==sum(ports.values()),'alias'); drivers={}; types=Counter()
    for cell in mod['cells'].values():
        kind=cell['type']; need(re.fullmatch('LUT[1-6]|MUXF[789]|INV',kind),'unexpected primitive '+kind); types[kind]+=1
        src=[];out=[]
        for n,bits in cell['connections'].items(): (src if cell['port_directions'][n]=='input' else out).extend(bits)
        need(len(out)==1 and out[0] not in drivers,'driver'); drivers[out[0]]=src
    groups={'all':roots,'lane1_valid':select(lambda n:n=='io_req_1_valid'),'lane0_valid':select(lambda n:n=='io_req_0_valid'),
            'request_command':select(lambda n:n.startswith('io_req_') and n.endswith('_cmd')),'request_address':select(lambda n:n.endswith('bits_addr')),
            'mshr_state':select(lambda n:n.endswith('_state')),'queue_space':select(lambda n:n.endswith('_enq_ready'))}
    depths={}
    for n,starts in groups.items():
        @lru_cache(None)
        def depth(b):
            if b in starts: return 0
            if b in roots or b in ('0','1'): return -10000
            return 1+max(map(depth,drivers[b]))
        depths[n]=[x if x>=0 else None for x in map(depth,pins['o']['bits'])]
    return dict(cells=dict(sorted(types.items())),stages_to_ready_0_1=depths)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('kit','yosys','out'): ap.add_argument(n,type=Path)
    a=ap.parse_args(); kit=a.kit.resolve(strict=True);y=a.yosys.resolve(strict=True);out=a.out.resolve();abc=shutil.which('berkeley-abc'); need(abc,'missing ABC')
    need(not a.out.is_symlink() and not out.exists() and kit not in out.parents and out not in kit.parents,'need fresh disjoint output'); src=load(kit); p,c=src[P],src[C]; out.mkdir(mode=0o700)
    variants={'stock':(p,c),'lane_local':derive(p,c,False),'class_local':derive(p,c,True)}; pp,cc=variants['class_local']
    controls={'gate_idle_primary':(once(pp,'~io_req_1_valid & ((','(io_req_0_valid & ~io_req_1_valid) & (('),cc),
              'drop_lane1_cmd6':(once(pp," | (io_req_1_bits_uop_mem_cmd == 5'h6)) ?"," ) ?"),cc),
              'wrong_bank7_space':(once(pp,'(idx_matches_1_7 & vcu_open_7 )','(idx_matches_1_7 & vcu_open_6 )'),cc)}
    run=D['L']['cmd']; reference=None; marks={}; profiles={}; seals={}
    for label,(par,child) in {**variants,**controls}.items():
        cut,ports=extract(par,child); need(reference is None or ports==reference,'interface differs'); reference=ports
        (out/(label+'.v')).write_text(cut); seals[label]=dict(parent=H(par.encode()),child=H(child.encode()),cut=H(cut.encode()))
        if label in variants and label!='stock':
            d=out/label; d.mkdir(); (d/(P+'.sv')).write_text(par); (d/(C+'.sv')).write_text(child)
        if label!='stock':
            log=run(out,y,'proof_'+label,f'read_verilog -noautowire stock.v; rename top gold; read_verilog -noautowire {label}.v; rename top gate; proc; opt; miter -equiv -make_outputs -flatten gold gate cmp; hierarchy -check -top cmp; opt; check -assert; sat -prove trigger 0 -show gold_o -show gate_o cmp')
            good=label in variants; need(log.count('SAT proof finished - no model found: SUCCESS!')==int(good) and log.count('SAT proof finished - model found: FAIL!')==int(not good),'proof '+label)
            marks[label]='equivalent' if good else {key:re.search(r'^\s+\\'+key+r'\s+\d+\s+[0-9a-fA-F]+\s+([01]{2})\s*$',log,re.M)[1] for key in ('gold_o','gate_o')}
        if label in variants:
            log=run(out,y,'map_'+label,f'read_verilog -noautowire {label}.v; synth_xilinx -family xcup -flatten -top top; check -assert; write_json {label}.json');need(log.count('Running ABC command: berkeley-abc -s -f')==1,'mapper');profiles[label]=mapping(json.loads((out/(label+'.json')).read_bytes())['modules']['top'],ports)
        print('REVIEWED '+label,flush=True)
    res=dict(scope='Recovery MSHRFile two-lane ready outputs, eight child state/secondary-ready equations. Two-state, same-cycle, unrestricted inputs. XCUP mapped primitive depths only; not routed timing or a board score.',
             physical_sha256=D['SEAL'],parents_sha256={n:H(s.encode()) for n,s in src.items()},inputs_bits=sum(reference.values()),sha256=seals,proofs=marks,mapping=profiles,
             tools={n:H(Path(path).read_bytes()) for n,path in [('yosys',y),('abc',abc)]})
    (out/'result.json').write_text(json.dumps(res,indent=2)+'\n')


if __name__=='__main__': main()
