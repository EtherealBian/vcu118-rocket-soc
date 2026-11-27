#!/usr/bin/env python3
"""Retiming experiment on the sealed BOOM D-cache lane 1; never edit the build kit."""
import argparse
import csv
import json
import os
from hashlib import sha256
from pathlib import Path
import re
import subprocess

SEAL = 'ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456'
LEAF = 'fdd20681408038f71c070fc1e8776a43f4ba38af7d5814af6b8e5c61162031d2'
ENDPOINTS = 'df1c4915dbf7d2aa48b17bd232709d84b17582b38ff5b3d96b92c3a4d1b7f399'
NAME = 'BoomNonBlockingDCache'
LOAD = 's2_req_1_addr'
STORE = ['s%d_req_addr' % i for i in (3, 4, 5)]
Q = [LOAD] + STORE
D = ['s1_req_1_addr', 's2_req_0_addr'] + STORE[:2]
FLAG = ['vcu_ld1_eq%d' % i for i in (3, 4, 5)]
TB = Path(__file__).resolve().parents[1] / 'tests/mega_dcache_forward.sv'


def need(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return sha256(data).hexdigest()


def once(text, old, new):
    need(text.count(old) == 1, 'ambiguous site: ' + old)
    return text.replace(old, new)


def write(path, text):
    path.write_bytes(text.encode())


def equation(text, op, name):
    pat = (r'^  assign ' if op == '=' else r'^    ') + name + ' ' + op + r' ([^;\n]+);'
    lines = re.findall(pat, text, re.M)
    need(len(lines) == 1, 'unexpected driver: ' + name)
    return lines[0]


def derive(src):
    # Only equality moves. Valid qualification, S3>S4>S5 priority, data, lane 0,
    # AMO feedback and the architectural load-response formatter stay as written.
    stock = equation(src, '=', 's2_data_word_1')
    candidate = stock
    extra = []
    for q, d in zip(Q, D):
        need(equation(src, '<=', q) == d, 'different address pipeline')
    for k, (addr, flag) in enumerate(zip(STORE, FLAG)):
        candidate = once(candidate, LOAD+'[39:3] == '+addr+'[39:3]', flag)
        extra.append('    '+flag+' <= '+D[0]+'[39:3] == '+D[k+1]+'[39:3];')
    need(all(f not in src for f in FLAG), 'flag name collision')
    anchor = '  assign s2_data_word_1 = '+stock+';'
    patch = '\n'.join('  reg '+f+';' for f in FLAG)+'\n  always @(posedge clock) begin\n'+'\n'.join(extra)+'\n  end\n'
    return once(src, anchor, patch+'  assign s2_data_word_1 = '+candidate+';')


def cut(text, tag, alt):
    # Split time at one active edge. For example s3_req_addr on a D RHS is
    # *before* that edge; the same spelling on the output RHS is *after* it.
    # The original source is pinned, and its four address assignments are
    # unconditional in the same positive-edge block. No reset assumptions.
    ds = ['pre_'+s for s in D]
    post = [s+'_valid' for s in ('s3','s4','s5')]
    words = [s+'_req_data' for s in ('s3','s4','s5')]
    ports = ['input clock'] + ['input [39:0] '+s for s in ds] + ['input '+s for s in post] + ['input [63:0] '+s for s in words+['s2_data_word_prebypass_1']] + ['output [63:0] s2_data_word_1']
    lines = ['module '+tag+'('+', '.join(ports)+');'] + ['reg [39:0] '+q+';' for q in Q]
    for f in FLAG if alt else []:
        lines.append('reg '+f+';')
    lines.append('always @(posedge clock) begin')
    for q in Q+(FLAG if alt else []):
        rhs = equation(text, '<=', q)
        rhs = re.sub(r'\b(?:'+ '|'.join(D) +r')\b', lambda m:'pre_'+m[0], rhs)
        lines.append('  '+q+' <= '+rhs+';')
    lines += ['end', 'assign s2_data_word_1 = '+equation(text, '=', 's2_data_word_1')+';', 'endmodule']
    return '\n'.join(lines)+'\n', ports


def run_cmd(folder, cmd, label):
    p = subprocess.run(cmd,cwd=folder,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
    (folder/(label+'.log')).write_bytes(p.stdout)
    need(p.returncode == 0, label+' failed; inspect private log')
    return p.stdout.decode(errors='replace').replace('\r','')


def prove(folder, tool, src, alt):
    common, ports = cut(src, 'gold', False)
    inputs = [port.split()[-1] for port in ports[:-1]]
    top = ('module step('+', '.join(ports[:-1]+['output mismatch'])+');\nwire [63:0] x,y;\n'+
           'gold g('+', '.join(inputs+['x'])+');\ngate a('+', '.join(inputs+['y'])+');\nassign mismatch=|(x^y);\nendmodule\n')
    first = equation(alt, '<=', FLAG[0]); selected = equation(alt, '=', 's2_data_word_1')
    # Inject errors separately in priority selection, the launch stage and two
    # address-bit boundaries, then require a concrete SAT counterexample in each.
    variants = {'retimed':alt, 'late_store_address':once(alt, first+';', first.replace(D[1],D[2])+';'),
                'include_byte_offset':once(alt, first+';',first.replace('[39:3]','[39:0]')+';'),
                'omit_bit19':once(alt, first+';', ' && '.join('('+first.replace('[39:3]',sl)+')' for sl in ('[39:20]','[18:3]'))+';'),
                'swapped_tags':once(alt,selected+';',selected.replace(FLAG[0], 'TEMP').replace(FLAG[1],FLAG[0]).replace('TEMP',FLAG[1])+';')}
    results={}
    for case, rtl in variants.items():
        v,_=cut(rtl,'gate',True)
        write(folder/(case+'.v'),common+v+top)
        cmds=f'read_verilog -noautowire {case}.v\nhierarchy -check -top step\nproc; flatten; opt; check -assert\nsat -seq 2 -prove-skip 1 -prove mismatch 0 -show-inputs -show-outputs step\n'
        write(folder/(case+'.ys'),cmds)
        log=run_cmd(folder,[str(tool),'-Q','-T','-s',case+'.ys'],case)
        decisions=(log.count('SAT proof finished - no model found: SUCCESS!'),log.count('SAT proof finished - model found: FAIL!'))
        need(decisions == ((1,0) if case=='retimed' else (0,1)),case+' unexpected SAT decision')
        results[case]='equivalent_after_one_edge' if case=='retimed' else 'counterexample'
    return dict(scope='Binary one-edge transition of lane-1 forwarding word; arbitrary four independent pre-edge address buses and arbitrary post-edge valid, store words and fallback. Not the entire cache.', decisions=results, tool=subprocess.check_output([str(tool),'-V'],text=True).strip(), tool_sha256=digest(tool.read_bytes()))


def remaining_mshr(kit, folder, tool, src, alt, seal):
    # Check another same-cycle consumer before recommending the forwarding change.
    # The real MSHR slot outputs are the boundary, not a model of their reachable states.
    name='BoomMSHRFile'; raw=(kit/'rtl'/(name+'.sv')).read_bytes(); h=digest(raw)
    need((h+'  rtl/'+name+'.sv').encode() in seal.splitlines(),'unsealed MSHR parent')
    s=raw.decode(); nodes=[]; ports=[]; pins=[]
    for parent in (src,alt):
        for port,net in [('io_req_1_bits_addr',LOAD),('io_block_hit_1','_mshrs_io_block_hit_1')]:
            need(len(re.findall(r'^    \.'+port+r'\s+\('+net+r'\),',parent,re.M))==1,'missing real MSHR connection')
    for i in range(8):
        for field, width, expr in [('idx_valid',1,'active'),('tag_valid',1,'active'),('idx_bits',6,'base[11:6]'),('tag_bits',28,'base[39:12]')]:
            n=f'_mshrs_{i}_io_'+field
            ports.append('input '+(f'[{width-1}:0] ' if width>1 else '')+n)
            pins.append('.'+n+'('+(f'(slot==3\'d{i})' if expr=='active' else expr)+')')
        for n in [f'idx_matches_1_{i}',f'_tag_matches_1_{i}_T_1']:
            nodes.append('wire '+n+' = '+equation(s,'=',n)+';')
    for n in ['idx_match_1','tag_match_1']:
        eq=re.findall(r'^  wire\s+'+n+r' = ([^;\n]+);',s,re.M);need(len(eq)==1,'unexpected match reduction')
        nodes.append('wire '+n+' = '+eq[0]+';')
    module=['module m('+', '.join(ports+['input [39:0] io_req_1_bits_addr','output io_block_hit_1'])+');',*nodes,
            'assign io_block_hit_1 = '+equation(s,'=','io_block_hit_1')+';','endmodule',
            'module witness(input [39:0] base,input [2:0] slot,output ok); wire a,b;']
    for n,addr in [('a','base'),('b',"(base ^ 40'h80000)")]:
        module.append('m u'+n+'('+', '.join(pins+['.io_req_1_bits_addr('+addr+')','.io_block_hit_1('+n+')'])+');')
    write(folder/'residual.v','\n'.join(module+['assign ok=a & ~b; endmodule','']))
    script='read_verilog -noautowire residual.v\nhierarchy -check -top witness\nproc; flatten; opt; check -assert\nsat -verify -prove ok 1 witness\n'
    write(folder/'residual.ys',script);log=run_cmd(folder,[str(tool),'-Q','-T','-s','residual.ys'],'residual')
    need(log.count('SAT proof finished - no model found: SUCCESS!')==1,'no decoded residual dependence')
    return dict(mshr_sha256=h, bit=19,slots=8,observation='Unchanged MSHR io_block_hit_1: for each sole valid matching slot and any base, toggling bit 19 changes 1 to 0. No RF endpoint or timing attribution.')


def simulate(kit, folder, tools, src, alt, seal):
    children=sorted(set(re.findall(r'^  (\w+) \w+ \(',src,re.M)))
    need(len(children)==13,'unexpected direct child types')
    headers=[]; hashes={}
    for name in children:
        data=(kit/'rtl'/(name+'.sv')).read_bytes(); hashes[name]=digest(data)
        need((hashes[name]+'  rtl/'+name+'.sv').encode() in seal.splitlines(),'unsealed child')
        header=re.findall(r'^module '+name+r'\(.*?^\);',data.decode(),re.M|re.S)
        need(len(header)==1,'unsupported child interface')
        headers.append(header[0]+'\nendmodule\n')
    write(folder/'children.sv','\n'.join(headers)); write(folder/'gold.sv',src)
    write(folder/'candidate.sv',once(alt,'module '+NAME+'(','module RetimedDCache('))
    (folder/'tb.sv').write_bytes(TB.read_bytes())
    def call(name,args):
        text=run_cmd(folder,[str(tools/'bin'/(name+('.bat' if os.name=='nt' else ''))),*args],name)
        need(not re.search(r'(?im)^\s*(fatal:|error:)',text),name+' failed; inspect private log')
        return text
    call('xvlog',['--sv','-d','SYNTHESIS','children.sv','gold.sv','candidate.sv','tb.sv'])
    e=call('xelab',['tb','--mt','off','--timescale','1ps/1ps','-s','dcache'])
    need('Vivado Simulator v2024.2' in e and 'Built simulation snapshot dcache' in e,'unexpected elaboration')
    log=call('xsim',['dcache','--runall'])
    m=re.findall(r'^DCACHE_PASS edges=(\d+) binary_cases=(\d+) single_bit_misses=(\d+) x_cases=(\d+) partial_x_words=(\d+)\s*$',log,re.M)
    need(len(m)==1 and '$finish called' in log,'incomplete parent simulation')
    edges,cases,misses,xc,xw=map(int,m[0]);need((cases,misses,xc)==(64,111,6) and edges==4*(cases+misses+xc) and xw==4,'incomplete coverage')
    return dict(scope='Clocked source parents, stub child interfaces and driven internal inputs. Compare forwarding and cached load data, not a cache transaction or SoC test.', simulator='Vivado Simulator v2024.2',child_interface_sha256=hashes,fixture_sha256=digest(TB.read_bytes()),edges=edges,masked_address_and_valid_cases=cases,one_bit_misses=misses,four_state_cases=xc,partial_unknown_expected_words=xw)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['proof','parent'])
    for n in ('kit','archived_tsv','tool','out'):p.add_argument(n,type=Path)
    a=p.parse_args();kit,tab,tool,out=[x.resolve() for x in (a.kit,a.archived_tsv,a.tool,a.out)]
    need(not out.exists() and all(x not in out.parents and x!=out for x in (kit,tool)), 'fresh, separate output required')
    seal=(kit/'CANDIDATE.sha256').read_bytes(); raw=(kit/'rtl'/(NAME+'.sv')).read_bytes()
    need(digest(seal)==SEAL and digest(raw)==LEAF and (LEAF+'  rtl/'+NAME+'.sv').encode() in seal.splitlines(),'wrong parent or kit')
    need(digest(tab.read_bytes())==ENDPOINTS,'wrong archived routed endpoints')
    with tab.open() as f: rows=[r for r in csv.DictReader(f,delimiter='\t') if r['from'].endswith('/dcache/s2_req_1_addr_reg[19]/C')]
    need(len(rows)==5 and all(r['to'].endswith('/D') and '/iregfile/regfile_ext/Memory_reg[' in r['to'] for r in rows),'wrong RF endpoint family')
    src=raw.decode();alt=derive(src);out.mkdir();write(out/('candidate-'+NAME+'.sv'),alt)
    rn=prove(out,tool,src,alt) if a.mode=='proof' else simulate(kit,out,tool,src,alt,seal)
    if a.mode=='proof': rn['remaining_dependency']=remaining_mshr(kit,out,tool,src,alt,seal)
    rn.update(kit_sha256=SEAL,parent_sha256=LEAF,candidate_sha256=digest(alt.encode()),archive_tsv_sha256=ENDPOINTS,archived_endpoints=[{k:r[k].split('/')[-2] if k=='to' else r[k] for k in ('slack_ns','logic_levels','to')} for r in rows])
    write(out/'result.json',json.dumps(rn,indent=2)+'\n');print('DCACHE_RESULT',a.mode,rn['candidate_sha256'])


if __name__=='__main__': main()
