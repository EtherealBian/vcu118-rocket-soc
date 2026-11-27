#!/usr/bin/env python3
"""Map identical four-port INT scheduler cuts to xcup primitives (not routed STA).

Keep all real grant sources, independent requests and FU inputs, every per-slot
acknowledgment and port valid. Include the exact uopc + dst_rtype output logic
of each port by default. --full-payload includes all 802 output data bits.
"""
import argparse
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

G=runpy.run_path(str(Path(__file__).with_name('prove-mega-issue-grants.py')));M=G['M']


def readout(fields):
    return {'ack':40,'valid':4,**{f'io_iss_uops_{p}_{n}':width for (p,n),width in fields.items()}}


def fixture(stock,variant,fields):
    gs=M['grants'](stock);arb,ins=M['cone'](stock,gs)
    if '  wire [39:0] vcu_req0;' in variant:arb=G['extract_changed'](variant,gs,ins).replace('module candidate(', 'module arb(',1)
    names=[s.split()[-1] for s in ins]; pins=set(names); widths={}
    for (_,n),w in fields.items():
        if widths.setdefault(n,w)!=w:raise ValueError('inconsistent field width across ports')
    for n,w in widths.items():
        for i in range(40):
            k=f'_slots_{i}_io_uop_{n}'
            # FU code is both a selected payload and the *same* slot input to arbitration.
            if k in pins:
                if f'input [{w-1}:0] {k}' not in ins:raise ValueError('overlapping inputs differ in width')
            else:pins.add(k);ins.append(f'input [{w-1}:0] {k}')
    outputs=[f'output [{w-1}:0] {n}' for n,w in readout(fields).items()]
    nets=[f'wire [39:0] gr{p};' for p in range(4)];nets+=['arb a('+','.join(names+[f'gr{p}' for p in range(4)])+');']
    for p in range(4):
        nets+=['wire '+name+f' = gr{p}[{i}];' for i,name in enumerate(gs[p])]
        nets+=[f'wire io_iss_valids_{p} = |gr{p};',f'assign valid[{p}] = io_iss_valids_{p};']
    nets+=['assign ack = gr0 | gr1 | gr2 | gr3;']
    rhs={}
    for m in M['FIELD'].finditer(variant):
        key=int(m[2]),m[3]
        if key in rhs:raise ValueError('duplicate output equation')
        rhs[key]=m[4]
    for p,n in fields:nets+=[f'assign io_iss_uops_{p}_{n} = '+rhs[p,n]+';']
    return arb+'module top('+', '.join(ins+outputs)+');\n'+'\n'.join(nets)+'\nendmodule\n'


def topology(top,expected):
    ports=top['ports'];drivers={};cells=Counter();sources={b for p in ports.values() if p['direction']=='input' for b in p['bits']}
    for c in top['cells'].values():
        kind=c['type']
        if not re.fullmatch(r'LUT[1-6]|MUXF[789]|INV',kind):raise ValueError('unexpected mapped primitive: '+kind)
        cells[kind]+=1
        if any(d not in ('input','output') for d in c['port_directions'].values()):raise ValueError('unexpected primitive direction')
        con=c['connections']; dirs=c['port_directions']
        if set(con)!=set(dirs) or any(len(vs)!=1 for vs in con.values()) or list(dirs.values()).count('output')!=1 or 'input' not in dirs.values():
            raise ValueError('expected scalar pins on a single-output combinational primitive')
        inputs=[v for p,vs in con.items() if dirs[p]=='input' for v in vs]
        for port,vs in c['connections'].items():
            if c['port_directions'][port]=='output':
                for v in vs:
                    if not isinstance(v,int) or v in drivers or v in sources:raise ValueError('invalid or multiple drivers')
                    drivers[v]=inputs
    visiting=set()
    @lru_cache(None)
    def depth(bit):
        if bit in sources or bit in ('0','1'):return 0
        if bit not in drivers:raise ValueError('floating, unknown, or missing driver')
        if bit in visiting:raise ValueError('combinational loop in mapped cone')
        visiting.add(bit);value=1+max(map(depth,drivers[bit]));visiting.remove(bit);return value
    if any(p['direction'] not in ('input','output') for p in ports.values()):raise ValueError('unsupported top-level direction')
    for bit in drivers:depth(bit)  # also reject floating and cyclic unused logic
    out={n:[depth(b) for b in p['bits']] for n,p in ports.items() if p['direction']=='output'}
    if {n:len(bs) for n,bs in out.items()}!=expected:raise ValueError('unexpected readout')
    return dict(cells=dict(sorted(cells.items())),total=sum(cells.values()),max_primitive_levels={n:max(bs) for n,bs in out.items()})


def review_cut(directory,fields):
    # Match the ABC actually called by this packaged Yosys rather than merely
    # hashing an unrelated copy on PATH. Also audit the complete pre-mapping IO.
    invocations=[row for row in (directory/'map.log').read_text().splitlines() if row.startswith('Running ABC command:')]
    if invocations!=['Running ABC command: berkeley-abc -s -f <abc-temp-dir>/abc.script 2>&1']:
        raise ValueError('unrecognized ABC invocation')
    model=json.loads((directory/'mapped.json').read_bytes())['modules']['top'];ports=model['ports']
    expected={f'io_fu_types_{p}':10 for p in (0,2,3)}
    for i in range(40):
        expected[f'_slots_{i}_io_request']=1;expected[f'_slots_{i}_io_uop_fu_code']=10
        for (_,n),w in fields.items():
            if expected.setdefault(f'_slots_{i}_io_uop_{n}',w)!=w:raise ValueError('inconsistent shared field width')
    pins={n:p['bits'] for n,p in ports.items() if p['direction']=='input'}; bits=[b for bs in pins.values() for b in bs]
    if {n:len(bs) for n,bs in pins.items()}!=expected or len(bits)!=len(set(bits)) or not all(isinstance(b,int) for b in bits):
        raise ValueError('unexpected cut inputs, widths or aliases')
    return topology(model,readout(fields))


def run(kit,out,yosys,full=False):
    digest=M['digest'];unit=(kit/'rtl'/M['NAME']).read_bytes();lock=(kit/'CANDIDATE.sha256').read_bytes();src=unit.decode()
    if digest(unit)!=M['UNIT'] or digest(lock)!=M['KIT'] or (M['UNIT']+'  rtl/'+M['NAME']) not in lock.decode().splitlines():raise ValueError('unreviewed physical source')
    out.mkdir();abc=shutil.which('berkeley-abc');v=subprocess.check_output([yosys,'-V'],text=True).strip()
    if not abc or v!='Yosys 0.9 (git sha1 1979e0b)' or subprocess.check_output([abc,'-c','version'],text=True).splitlines()[-1]!='UC Berkeley, ABC 1.01':raise ValueError('unexpected toolchain')
    mux,gs,all_fields=M['derive'](src);records={}
    fields={(p,n):w for (p,n),(w,default) in all_fields.items() if full or n in ('uopc','dst_rtype')}
    if (len(fields),sum(fields.values()))!=((159,802) if full else (8,36)):raise ValueError('incomplete payload')
    for name,unit in [('stock',src),('onehot_payload',mux),('grouped_grants',G['replace_cone'](src,gs,G['parallel_select'](gs))),('both',G['replace_cone'](mux,gs,G['parallel_select'](gs)))]:
        d=out/name;d.mkdir();vlog=fixture(src,unit,fields).encode();(d/'cut.v').write_bytes(vlog)
        cmds='read_verilog -noautowire cut.v; synth_xilinx -top top -family xcup -flatten; select -assert-none t:$mem t:$dff t:$lut; check -assert; write_json mapped.json'
        with (d/'map.log').open('wb') as f:subprocess.run([yosys,'-Q','-T','-p',cmds],cwd=d,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=1500 if full else 180)
        cells=review_cut(d,fields);records[name]=dict(unit_sha256=digest(unit.encode()),cut_sha256=digest(vlog),**cells)
    desc='All 802 issue output payload bits.' if full else '9 selected payload bits/port (36 total).'
    return dict(scope='Yosys/ABC unplaced combinational cuts. 40 slots, 4 ports, all 40 grant acknowledgments + 4 valid bits. '+desc+' Independent slot inputs, not full slot storage, compaction or downstream consumers. Primitive levels are not delay, occupied CLBs, full-core QoR or a board measurement.',payload_bits=sum(fields.values()),board_input_seal=M['KIT'],solver=v,yosys_sha256=digest(Path(yosys).read_bytes()),abc_sha256=digest(Path(abc).read_bytes()),profiles=records)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('out',type=Path);p.add_argument('--yosys',default='yosys');p.add_argument('--full-payload',action='store_true',help='map all 159 real fields, including signals which downstream logic may prune');a=p.parse_args();tool=shutil.which(a.yosys)
    if not tool:p.error('yosys not found')
    result=run(a.kit,a.out,str(Path(tool).resolve()),a.full_payload);(a.out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print('FOUR_MAPPED_CUTS_NO_TIMING')
