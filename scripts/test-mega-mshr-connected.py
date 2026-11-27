#!/usr/bin/env python3
"""Check the sealed MSHR-ready changes through the cache and the real LSU miss output."""
import argparse
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
import re
import runpy
import shutil

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'test-mega-mshr-ready.py'))
D=M['D']; h=M['H']; need=D['need']; once=D['once']; width=D['width']


def connected(name,p,c,queue,src):
    dc=D['clean'](src['dc']); wires=M['pins'](dc,M['P'],'mshrs')
    block=re.findall(r'^  BoomMSHRFile mshrs \((.*?)^  \);',dc,re.M|re.S); need(len(block)==1,'wrong MSHRFile instance')
    def expr(n):
        match=re.findall(r'^    \.'+n+r'\s+\((.*)\),?$',block[0],re.M); need(len(match)==1,'ambiguous expression '+n); return match[0]
    mr,mp=M['extract'](p,c,queue); rsp,rp=D['extract'](src)
    need(expr('io_req_is_probe_0')=='_mshrs_io_req_is_probe_1_T & s2_valid_REG' and D['equation'](dc,'_mshrs_io_req_is_probe_1_T')=="s2_type == 3'h1",'probe qualifier')
    ext={'dc_s2_replaced_way_en_REG':3}; mconn={'io_req_is_probe_0':"((dc_s2_type == 3'h1) & dc_s2_valid_REG)"}; rconn={}; ins={}
    need(D['equation'](dc,'s2_replaced_way_en')=="8'h1 << s2_replaced_way_en_REG",'replacement way encoder')
    for i in (0,1):
        for field,expected in [('bits_addr',f's2_req_{i}_addr'),('bits_uop_mem_cmd',f's2_req_{i}_uop_mem_cmd'),('valid',f'mshrs_io_req_{i}_valid'),('ready',f'_mshrs_io_req_{i}_ready')]:
            n=f'io_req_{i}_{field}'; need(wires[n]==expected,'mismatched port '+n)
        n=f's2_tag_match_way_{i}'; need(expr(f'io_req_{i}_bits_way_en')==f'(|{n}) ? {n} : s2_replaced_way_en','way select'); need(wires[f'io_secondary_miss_{i}']==f'_mshrs_io_secondary_miss_{i}','secondary miss link')
        ext['dc_'+n]=8; ext[f'dc_s2_req_{i}_addr']=40
        mconn.update({f'io_req_{i}_bits_addr':f'dc_s2_req_{i}_addr',f'io_req_{i}_bits_uop_mem_cmd':f'dc_s2_req_{i}_uop_mem_cmd',f'io_req_{i}_valid':f'v[{i}]',f'io_req_{i}_bits_way_en':f"((|dc_{n}) ? dc_{n} : (8'h1 << dc_s2_replaced_way_en_REG))"})
        rconn.update({f'dc__mshrs_io_req_{i}_ready':f'm[{i}]',f'dc__mshrs_io_secondary_miss_{i}':f'm[{2+i}]'})
    for n,w in ext.items(): need(D['lhs'](dc,n[3:])==w,'cut register '+n)
    need(set(mconn)<=set(mp) and set(rconn)<=set(rp),'interface changed')
    def collect(ports,conn):
        for n,w in sorted(ports.items()):
            if n not in conn:
                need(n not in ins,'ambiguous external net'); ins[n]=w; conn[n]=n
    collect(mp,mconn); collect(rp,rconn); need(not set(ext)&set(ins),'alias');ins.update(ext)
    def inst(mod, con): return mod+' u_'+mod+'('+', '.join('.'+k+'('+v+')' for k,v in sorted(con.items()))+');'
    # Module names are unique across both sides of the formal miter.
    mn='mshr_'+name; rn='resp_'+name
    mr=once(mr,'module top(','module '+mn+'('); rsp=once(rsp,'module top(','module '+rn+'(')
    rsp=once(rsp,'output [2:0] o);','output [1:0] valid, output [2:0] o);'); rsp=once(rsp,'endmodule','assign valid={dc_mshrs_io_req_1_valid,dc_mshrs_io_req_0_valid};\nendmodule')
    top='module top('+', '.join('input '+width(w)+n for n,w in sorted(ins.items()))+', output [2:0] o);\nwire [1:0] v; wire [3:0] m;\n'+inst(mn,{**mconn,'o':'m'})+'\n'+inst(rn,{**rconn,'valid':'v','o':'o'})+'\nendmodule\n'
    return top+mr+rsp,ins


def mapped(mod,ports):
    pp=mod['ports']; need(set(pp)==set(ports)|{'o'} and len(pp['o']['bits'])==3,'mapped interface'); drivers={}; cells=Counter()
    for v in mod['cells'].values():
        t=v['type']; need(re.fullmatch('LUT[1-6]|MUXF[789]|INV|MUXCY|XORCY',t),'unexpected primitive '+t); cells[t]+=1
        ins=[]; outs=[]
        for k,bs in v['connections'].items(): (ins if v['port_directions'][k]=='input' else outs).extend(bs)
        need(len(outs)==1 and outs[0] not in drivers,'duplicate output'); drivers[outs[0]]=ins
    def bits(match): return {v for n in ports if match(n) for v in pp[n]['bits']}
    roots=bits(lambda n:True); need(len(roots)==sum(ports.values()),'unexpected port alias'); groups={'all':roots,'branch_mask':bits(lambda n:n=='dc_io_lsu_brupdate_b1_mispredict_mask'),'lane1_address':bits(lambda n:n=='dc_s2_req_1_addr'),'mshr_state':bits(lambda n:n.endswith('_state')),'rpq_ptr_full':bits(lambda n:re.match(r'q\d+_',n)),'lsu_table':bits(lambda n:n.endswith('_flat'))}; depths={}
    for k,starts in groups.items():
        need(starts,'empty group '+k)
        @lru_cache(None)
        def depth(b):
            if b in starts: return 0
            if b in roots or b in ('0','1'): return -10000
            return 1+max(map(depth,drivers[b]))
        depths[k]=[v if v>=0 else None for v in map(depth,pp['o']['bits'])]
    return dict(cells=dict(sorted(cells.items())),primitive_depth=depths)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('kit','yosys','out'): ap.add_argument(n,type=Path)
    a=ap.parse_args(); kit=a.kit.resolve(strict=True); y=a.yosys.resolve(strict=True); out=a.out.resolve(); abc=shutil.which('berkeley-abc'); need(abc,'missing ABC')
    need(not a.out.is_symlink() and not out.exists() and kit not in out.parents and out not in kit.parents,'need disjoint fresh output'); src,ids=D['kit_sources'](kit); D['verify_links'](src); parents=M['load'](kit); p,c,q=[parents[M[n]] for n in ('P','C','Q')]; ids.update({n:h(s.encode()) for n,s in parents.items()}); out.mkdir(mode=0o700)
    cp,cc=M['derive'](p,c,True); split=D['derive'](src['dc'],True)
    variants={'stock':(p,c,src['dc']), 'class_local':(cp,cc,src['dc']), 'split_rsp':(p,c,split),'class_and_rsp':(cp,cc,split)}
    controls={'bank7_space':(once(cp,'(idx_matches_1_7 & vcu_open_7 )','(idx_matches_1_7 & vcu_open_6 )'),cc,src['dc']), 'bank7_permitted':(once(cp,'(idx_matches_1_7 & vcu_permitted_7 )','(idx_matches_1_7 & vcu_permitted_6 )'),cc,src['dc']), 'wrong_lane':(once(once(cp,'assign io_req_1_ready = io_req_1_ready_0;', 'assign io_req_1_ready = io_req_0_ready_0;'),'assign io_req_0_ready = io_req_0_ready_0;', 'assign io_req_0_ready = io_req_1_ready_0;'),cc,src['dc'])}
    checks={}; maps={}; cuts={}; reference=None
    for name,(par,child,cache) in {**variants,**controls}.items():
        cut,ports=connected(name,par,child,q,{**src,'dc':cache}); need(reference is None or reference==ports,'interface differs'); reference=ports; cuts[name]=h(cut.encode()); (out/(name+'.v')).write_bytes(cut.encode())
        if name!='stock': checks[name]=D['proof'](out,y,name,'stock',name,name in variants or name=='bank7_space')
        if name in variants:
            log=D['L']['cmd'](out,y,'map_'+name,f'read_verilog -noautowire {name}.v; hierarchy -check -top top; proc; flatten; check -assert; synth_xilinx -family xcup -flatten -top top; check -assert; write_json {name}.json'); need(log.count('Running ABC command: berkeley-abc -s -f')==1,'mapper'); maps[name]=mapped(json.loads((out/(name+'.json')).read_bytes())['modules']['top'],ports)
        print('VERIFIED '+name,flush=True)
    result=dict(scope='Same-cycle, two-state MSHR/queue-state -> two D-cache response valids and LSU speculative miss. S2 hits and remaining cut inputs free. XCUP primitive graph, not routed timing or board scores.',physical_sha256=D['SEAL'],parents_sha256=ids,inputs_bits=sum(reference.values()),outputs_lsb_first=[n for _,n in D['OUT']],cuts_sha256=cuts,proofs=checks,mapping=maps,tools_sha256={'yosys':h(y.read_bytes()),'abc':h(Path(abc).read_bytes())}); (out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())


if __name__=='__main__': main()
