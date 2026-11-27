#!/usr/bin/env python3
"""Reorder the sealed four-port BOOM INT grant computation; keep slot age priority.

The original loops over slots, then ports. With the same total slot and port
priorities, port 0 takes its earliest eligible slot; deleting that slot and port
leaves the same problem for port 1, etc. Check that reasoning against the *real*
622 statements, not just two behavioral implementations of the algorithm.
"""
import argparse
import json
from pathlib import Path
import re
import runpy

M=runpy.run_path(str(Path(__file__).with_name('prove-mega-issue-mux.py')))


def parallel_select(gs, block=8, broken=False):
    if block not in (4,8):raise ValueError('unsupported group size')
    code=[]
    for p in range(4):
        name=f'vcu_req{p}';code.append(f'wire [39:0] {name};')
        for i in range(40):
            fu=f'_slots_{i}_io_uop_fu_code';match=f'(|({fu} & io_fu_types_{p}))' if p!=1 else f'({fu}[0] | {fu}[5])'
            exclude='' if p==0 else ' & ~('+' | '.join(gs[k][i] for k in range(p))+')'
            code.append(f'assign {name}[{i}] = _slots_{i}_io_request & {match}{exclude};')
        for i in range(40):
            start=i//block*block
            older=(' & ~(|'+f'{name}[{start-1}:0])') if start else ''
            local=(' & ~(|'+f'{name}[{i-1}:{start}])') if start<i else ''
            if broken and (p,i)==(0,1):local=''  # omit older slot 0
            code.append(f'wire {gs[p][i]} = {name}[{i}]{older}{local};')
    for i in range(40):code.append(f'assign issue_slots_{i}_grant = '+' | '.join(gs[p][i] for p in reversed(range(4)))+';')
    return '\n'.join('  '+c for c in code)


def replace_cone(src,gs,new):
    lines=src.splitlines(keepends=True)
    a,=[i for i,s in enumerate(lines) if re.match(r'^  wire\s+_GEN_141 = ',s)]
    b,=[i for i,s in enumerate(lines) if s.startswith('  assign issue_slots_39_grant = ')]
    if b-a+1!=622:raise ValueError('grant cone boundary changed')
    symbols=lambda ss:set(re.findall(r'\b(?:_GEN_\d+|_can_allocate_T_\d+)\b',re.sub(r'//[^\n]*','',''.join(ss))))
    used=symbols(lines[:a]+lines[b+1:]) & symbols(lines[a:b+1]);outs=set(sum(gs,[]))
    if used!=outs:raise ValueError('replacement would disconnect an external signal')
    return ''.join(lines[:a])+new+'\n'+''.join(lines[b+1:])


def extract_changed(changed,gs,ins):
    # Independently delimit the code that will be compiled into the candidate.
    a=changed.index('  wire [39:0] vcu_req0;');b=changed.index(';',changed.index('  assign issue_slots_39_grant = ',a))+1
    text=changed[a:b]; outs=['output [39:0] gr%d'%p for p in range(4)]
    return 'module candidate('+', '.join(ins+outs)+');\n'+'\n'.join('wire issue_slots_%d_grant;'%i for i in range(40))+'\n'+text+'\n'+'\n'.join('assign gr%d = {'%p+','.join(gs[p][::-1])+'};' for p in range(4))+'\nendmodule\n'


def miter(stock,variant,ins,p):
    top=stock+variant+'module top('+', '.join(ins+['output ok'])+');\n';args=[s.split()[-1] for s in ins]
    for module,prefix in [('arb','a'),('candidate','b')]:
        gs=[prefix+str(k) for k in range(4)];top+='wire [39:0] '+', '.join(gs)+';\n'+module+' '+prefix+'('+', '.join(args+gs)+');\n'
    # Previously proved lower ports may serve as induction hypotheses. No
    # assumptions about input requests, op encodings, busy state, or data.
    hyp=' || '.join(f'(a{k} != b{k})' for k in range(p))
    return top+'assign ok = '+(hyp+' || ' if hyp else '')+f'(a{p} == b{p});\nendmodule\n'


def run(kit,out,solver):
    raw=(kit/'rtl'/M['NAME']).read_bytes();lock=(kit/'CANDIDATE.sha256').read_bytes();digest=M['digest']
    if digest(raw)!=M['UNIT'] or digest(lock)!=M['KIT'] or (M['UNIT']+'  rtl/'+M['NAME']) not in lock.decode().splitlines():raise ValueError('unmatched sealed board input')
    src=raw.decode();gs=M['grants'](src);stock,ins=M['cone'](src,gs);out.mkdir();record={}
    mux,_,_=M['derive'](src)
    for label,broken in [('group8',False),('omit_slot0',True)]:
        actual=replace_cone(src,gs,parallel_select(gs,8,broken));variant=extract_changed(actual,gs,ins)
        if not broken:
            (out/'grant-only.sv').write_bytes(actual.encode());both=replace_cone(mux,gs,parallel_select(gs));(out/'grant-and-mux.sv').write_bytes(both.encode())
        for p in range(1 if broken else 4):
            name=f'{label}-port{p}';record[name]=M['proof'](out,name,miter(stock,variant,ins,p),solver,broken)
    return dict(scope='Two-state combinational proof of all 160 stock-vs-grouped grant bits for arbitrary real cone inputs. Standalone candidate; no change to the running implementation, no timing or score.',board_input_seal=M['KIT'],stock_sv_sha256=M['UNIT'],grant_only_sv_sha256=digest((out/'grant-only.sv').read_bytes()),grant_and_mux_sv_sha256=digest((out/'grant-and-mux.sv').read_bytes()),priority_group_slots=8,ports=4,slots=40,port_equivalence_under_previously_proved_ports=record)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--yosys',default='yosys');a=p.parse_args();r=run(a.kit,a.out,a.yosys);(a.out/'result.json').write_bytes((json.dumps(r,indent=2)+'\n').encode());print('GROUPED_GRANTS_EQUIVALENT_NOT_PHYSICAL_TIMING')
