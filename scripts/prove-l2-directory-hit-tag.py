#!/usr/bin/env python3
"""Compare three rewrites of the L2 directory return tag; do not touch the physical kit."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
TOPOLOGY = runpy.run_path(str(HERE/'map-mega-issue-cut.py'))['topology']
KIT = 'b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'
UNITS = {'Directory':'539577c8fb744ef1b37f4f6d738fb1e893b93c18582935366b08d28006140d99',
         'MSHR':'c18630c48a3b8986d30e2f576dbc22b233c08e4d5725a897932fd1749686d8e4',
         'InclusiveCacheBankScheduler':'a57cf1807fe92ad14c9bc3e8c497d3a14ca289b98430ac0aa0691ec47bad0e8d'}
OUTPUTS = {'io_result_bits_'+k:w for k,w in [('dirty',1),('state',2),('clients',1),('tag',16),('hit',1),('way',3)]}
BOUNDARY = {'tag':16,'set':10,'_cc_dir_RW0_rdata':160,'_write_q_io_deq_valid':1,
            **{'_victimLFSR_prng_io_out_'+str(i):1 for i in range(10)},
            **{'_write_q_io_deq_bits_'+n:w for n,w in [('set',10),('way',3),('data_tag',16),('data_state',2),('data_dirty',1),('data_clients',1)]}}


def need(ok, msg):
    if not ok: raise ValueError(msg)


def digest(data):
    return sha256(data).hexdigest()


def replace(src, old, new):
    need(src.count(old)==1, 'expected unique rewrite site')
    return src.replace(old,new)


def candidate(src):
    # Every selected valid SRAM way compared equal to the SAME registered tag.
    # (No one-hot hypothesis needed.) Preserve the non-SRAM-hit bypass/victim path.
    terms = [f"(_hits_T_{6+7*i} ? _cc_dir_RW0_rdata[{20*i+15}:{20*i}] : 16'h0)" for i in range(8)]
    prefix = 'assign io_result_bits_tag = (|hits) ? '
    return replace(src, prefix+' | '.join(terms)+' : _view__T_69 ?', prefix+'tag : _view__T_69 ?')


def partition(src, parallel=False):
    # Forwarded matching tags also equal tag, even when forwarded state is invalid.
    # A forwarded *victim* with a different tag must retain its data. An SRAM
    # hit (possibly a different way) still has priority over that victim.
    pattern = r"assign io_result_bits_tag = \(\|hits\) \? tag : _view__T_69 \? _write_q_io_deq_bits_data_tag : ([^;\n]+);"
    found = re.findall(pattern,src); need(len(found)==1,'missing hit-tag assignment'); victim, = found
    common = ("wire vcu_return_lookup = (|hits) | _io_result_bits_way_T_7;\n  "
              "wire vcu_forward_victim = setQuash & (_write_q_io_deq_bits_way == victimWay);\n  ")
    expr = ("({16{vcu_return_lookup}} & tag) | ({16{~vcu_return_lookup & vcu_forward_victim}} & _write_q_io_deq_bits_data_tag) | "
            "({16{~vcu_return_lookup & ~vcu_forward_victim}} & ("+victim+"))" if parallel else
            "vcu_return_lookup ? tag : vcu_forward_victim ? _write_q_io_deq_bits_data_tag : "+victim)
    return re.sub(pattern,lambda _:common+'assign io_result_bits_tag = '+expr+';',src)


def cut(src, name):
    text = re.sub(r'//[^\n]*', '', src)
    pins = []
    for direction,fields in [('input',BOUNDARY),('output',OUTPUTS)]:
        for n,w in fields.items():
            width = '' if w==1 else f'[{w-1}:0] '
            kind = r'(?:reg|wire)' if direction=='input' else 'output'
            need(len(re.findall(r'^  '+kind+r'\s+'+re.escape(width).replace(r'\ ',r'\s+')+n+r'\s*[,;]', text, re.M))==1, 'wrong source boundary: '+n)
            pins.append(f'{direction} {width}{n}')
    wires = re.findall(r'^  (wire\s+[^\n;]* = [^;\n]+;)',text,re.M)
    assigns = re.findall(r'^  (assign io_result_bits_\w+ = [^;\n]+;)',text,re.M)
    need(len(wires)==30+(2 if 'wire vcu_return_lookup =' in src else 0) and {x.split()[1] for x in assigns}==set(OUTPUTS) and len(assigns)==6, 'incomplete result expressions')
    return 'module '+name+'('+',\n'.join(pins)+');\n'+'\n'.join(wires+assigns)+'\nendmodule\n'


def run(kit,out,tool):
    lock = (kit/'CANDIDATE.sha256').read_bytes(); need(digest(lock)==KIT,'different physical input seal')
    inputs = {}
    for n,h in UNITS.items():
        p = 'rtl/'+n+'.sv'; b = (kit/p).read_bytes(); need(digest(b)==h and (h+'  '+p).encode() in lock.splitlines(), 'unexpected '+n); inputs[n]=b.decode()
    sched = re.sub(r'//[^\n]*','',inputs['InclusiveCacheBankScheduler'])
    instances = re.findall(r'^  MSHR mshrs_(\d+)\s*\((.*?)\n  \);',sched,re.M|re.S)
    need([i for i,_ in instances]==list(map(str,range(12))) and all(len(re.findall(r'\.io_directory_bits_tag\s*\(_directory_io_result_bits_tag\)',s))==1 for _,s in instances) and
         len(re.findall(r'\.io_result_bits_tag\s*\(_directory_io_result_bits_tag\)',sched))==1,'scheduler tag broadcast wiring')
    need(re.findall(r'^\s*meta_tag <= (\w+);',inputs['MSHR'],re.M)==['request_tag','io_directory_bits_tag'], 'unexpected MSHR tag writers')
    version = subprocess.check_output([tool,'-V'],text=True).strip(); abc=shutil.which('berkeley-abc')
    need(version=='Yosys 0.9 (git sha1 1979e0b)' and abc, 'unexpected synthesis tools')
    tool_hash=digest(Path(tool).read_bytes()); abc_hash=digest(Path(abc).read_bytes())
    need((tool_hash,abc_hash)==('f58d1dfcbc9b48a81357283e93b53e4c78415f6d28f227f0db34a79f316e6a64',
                               '6b6d93004494101bed191ddf29c411df55c50f990d7db56796767a3efbb03b09'),'different mapper binary')
    src=inputs['Directory']; alt=candidate(src); out.mkdir(mode=0o700)
    candidates = {'hit_tag':alt,'partition':partition(alt),'parallel':partition(alt,True)}
    for name,unit in candidates.items():
        (out/(name+'-Directory.sv')).write_bytes(unit.encode())
    versions = {'stock':src,**candidates,'wrong_hit':replace(alt,'? tag : _view__T_69',"? (tag ^ 16'h1) : _view__T_69"),
                'wrong_forward':replace(alt,': _view__T_69 ? _write_q_io_deq_bits_data_tag :',': _view__T_69 ? tag :'),
                'wrong_priority':replace(candidates['partition'],'vcu_return_lookup ? tag : vcu_forward_victim ?', 'vcu_return_lookup & ~vcu_forward_victim ? tag : vcu_forward_victim ?'),
                'wrong_mask':replace(candidates['parallel'],'~vcu_return_lookup & ~vcu_forward_victim','~vcu_forward_victim'),
                'wrong_victim':replace(alt, "((|_GEN) ? 16'h0 : _cc_dir_RW0_rdata[15:0])", "16'h0")}
    proofs={}; maps={}
    def yosys(d,cmd,log):
        p=d/log
        with p.open('xb') as f: subprocess.run([tool,'-Q','-T','-p',cmd],cwd=d,stdout=f,stderr=subprocess.STDOUT,timeout=120,check=True)
        return p.read_text()
    for k,v in versions.items():
        d=out/k; d.mkdir(); (d/'cut.v').write_text(cut(v,'top'))
        if k!='stock':
            (d/'gold.v').write_text(cut(src,'gold'))
            cmd='read_verilog -noautowire gold.v cut.v; miter -equiv -flatten gold top miter; hierarchy -top miter; opt; check -assert; sat -prove trigger 0 -show-inputs -show-outputs miter'
            log=yosys(d,cmd,'proof.log'); ok=k in candidates
            need(log.count('SAT proof finished - no model found: SUCCESS!')==int(ok) and log.count('SAT proof finished - model found: FAIL!')==int(not ok),'unexpected solver result: '+k)
            proofs[k]='equivalent' if ok else 'counterexample'
        if k=='stock' or k in candidates:
            log=yosys(d,'read_verilog -noautowire cut.v; hierarchy -check -top top; proc; check -assert; synth_xilinx -family xcup -flatten -top top; check -assert; write_json mapped.json','map.log')
            need([r for r in log.splitlines() if r.startswith('Running ABC command:')]==['Running ABC command: berkeley-abc -s -f <abc-temp-dir>/abc.script 2>&1'],'ABC invocation mismatch')
            top=json.loads((d/'mapped.json').read_bytes())['modules']['top']
            need({n:len(p['bits']) for n,p in top['ports'].items() if p['direction']=='input'}==BOUNDARY, 'mapped input mismatch')
            maps[k]=TOPOLOGY(top,OUTPUTS,allow_muxcy=True)
    result=dict(scope='Full 24-bit combinational directory result cone with independent two-state inputs. Unplaced primitive counts and levels only; not timing or a board run.',board_input_seal=KIT,source_sha256=UNITS,candidate_directory_sha256={n:digest(unit.encode()) for n,unit in candidates.items()},mshr_instances_on_shared_tag=len(instances),solver=version,yosys_sha256=tool_hash,abc_sha256=abc_hash,proofs=proofs,maps=maps)
    (out/'result.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('kit',type=Path); p.add_argument('out',type=Path); p.add_argument('--yosys',default='yosys'); a=p.parse_args()
    tool=shutil.which(a.yosys); need(tool,'Yosys is required'); run(a.kit.resolve(),a.out.resolve(),tool)
