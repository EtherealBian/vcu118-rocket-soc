#!/usr/bin/env python3
"""Derive and exercise the ten one-way board pads, never modify a sealed kit."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import os
import re
import subprocess

SEALS = ('b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959', 'ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456')
RPT = {'routed-drc.rpt':'5432682eef3f66fed23d763137203c535f049aab1c32fe9976914ffe18ca23b9', 'io.rpt':'e1d6b3491b1bca2a93611dcfaa41bc034adbfd0a94b42c136ca1696168e9c1e3', 'methodology.rpt':'58bdb85a73143514d2563ccb758f597566edea27a40a3ba0284e85b73ccc176e', 'check-timing.rpt':'c72de60720fc034eb5baa6c2b3ba1f50a187d66a60df4827fb58fb1ef9643f0b'}
PADS = {  # package pin, shell-side signal; never classify from pad name alone
    'uart_rxd': ('AW25','_io_uart_bbIn_rxd_a2b_b'), 'sdio_spi_dat_0': ('AW15','_a2b_4_b'),
    **{'jtag_jtag_'+k:(pin,'_jtagDebugSourceIn_'+k+'_a2b_b') for k,pin in [('TCK','AL12'),('TDI','AP15'),('TMS','AN15')]},
    'uart_txd': ('BB21','_chiptop0_uart_0_txd'), 'sdio_spi_clk': ('AV15','_chiptop0_spi_0_sck'),
    'sdio_spi_cs': ('AY15','_chiptop0_spi_0_dq_0_o'), 'sdio_spi_dat_3': ('AY14','_chiptop0_spi_0_cs_0'),
    'jtag_jtag_TDO': ('AM12','_chiptop0_jtag_TDO')}
INPUTS, OUTPUTS = list(PADS)[:5], list(PADS)[5:]
TOP = 'VCU118FPGATestHarness.sv'
MODS = ('AnalogToUInt_1.v','UIntToAnalog_1.v')
WRAP = r'(?ms)^  (AnalogToUInt_1|UIntToAnalog_1) (\w+) \([^\n]*\n(.*?)^  \);[^\n]*$'


def need(ok, why):
    if not ok: raise ValueError(why)


def h(raw): return sha256(raw).hexdigest()

def clean(src): return re.sub(r'//[^\n]*', '', src)


def read_kit(folder, seal):
    raw = (folder/'CANDIDATE.sha256').read_bytes(); need(h(raw)==seal, 'wrong kit')
    files = dict((p,s) for s,p in (line.split('  ',1) for line in raw.decode().splitlines()))
    wanted = ['rtl/'+n for n in (TOP,*MODS)] + [next(p for p in files if p.endswith('.shell.xdc'))]
    out = {}
    for p in wanted:
        data = (folder/p).read_bytes(); need(h(data)==files[p],'wrong sealed file: '+p); out[p]=data
    return out


def archive(folder):
    for f,s in RPT.items(): need(h((folder/f).read_bytes())==s,'wrong original routed report: '+f)
    drc, io, meth, check = [(folder/f).read_text() for f in RPT]
    rp = re.findall(r'^RPBF-3#\d+ Warning\n[^\n]*\nDevice port (\w+) expects both input and output buffering', drc,re.M)
    hp = re.findall(r'^HPDR-1#\d+ Warning\n[^\n]*\nHierarchical port\(pin\) (\w+) direction INOUT',meth,re.M)
    need(len(rp)==10 and set(rp)==set(PADS) and len(hp)==5 and set(hp)==set(OUTPUTS),'wrong native pad groups')
    for pad,(pin,_) in PADS.items():
        rows=[r.strip().strip('|').split('|') for r in io.splitlines() if re.match(r'^\| '+pin+r'\s*\|',r)]
        need(len(rows)==1 and [x.strip() for x in rows[0]][1:2]==[pad] and [x.strip() for x in rows[0]][5:7]==['BIDIR','LVCMOS18'], 'wrong native I/O: '+pad)
    need('PLCK-58#1 Warning' in drc and 'is locked to AL12' in drc and 'REQP-1618#1 Warning' in drc and 'txm/out_reg has IOB set to TRUE' in drc, 'different remaining issues')
    need('checking no_input_delay (5)' in check and 'checking no_output_delay (6)' in check,'different missing delays')


def derive(src):
    parts = {}; changed=src
    for m in re.finditer(WRAP,src):
        body = clean(m[3]); ports = dict(re.findall(r'\.(\w+)\s*\(([^()]*)\)',body)); p = ports['a']
        if p not in PADS: continue
        inp = p in INPUTS; sign='input' if inp else 'output'; net=PADS[p][1]
        need(p not in parts and m[1] == ('AnalogToUInt_1' if inp else 'UIntToAnalog_1'), 'wrong pad wrapper: '+p)
        need(ports==({'a':p,'b':net} if inp else {'a':p,'b':net,'b_en':"1'h1"}), 'not a single fixed direction: '+p)
        need(len(re.findall(r'\b'+p+r'\b',clean(src)))==2,'unaccounted pad reference: '+p)
        eq = f'assign {net} = {p};' if inp else f'assign {p} = {net};'
        changed,num = re.subn(r'(?m)^(  )inout(\s+'+p+r',)',r'\g<1>'+sign+r'\2',changed); need(num==1,'wrong pad declaration: '+p)
        changed=changed.replace(m[0],'  '+eq); parts[p]=(m[0],eq)
    need(set(parts)==set(PADS),'missing active pad')
    return changed,parts


def fixture(src, parts, typed):
    # Both variants are taken from their corresponding complete parent source.
    decl=[]; wires=[]; logic=[]
    for p,(_,n) in PADS.items():
        d=re.findall(r'(?m)^  (inout|input|output)\s+'+p+r',',src); need(len(d)==1,'missing pad')
        decl.append(d[0]+' wire '+p); block=parts[p][int(typed)]; need(src.count(block)==1,'missing pad body: '+p); logic.append(clean(block))
        if p in INPUTS: wires.extend([f'wire {n};',f'assign sense[{INPUTS.index(p)}] = {n};'])
        else: wires.append(f'wire {n} = launch[{OUTPUTS.index(p)}];')
    return ('module io_fixture('+', '.join(decl)+', input wire clk, input wire [4:0] drive, output reg [4:0] sample);\n'
            'reg [4:0] launch; wire [4:0] sense; always @(posedge clk) begin launch<=drive; sample<=sense; end\n'+
            '\n'.join(wires+logic)+'\nendmodule\n')


def prepare(old,new,reports,out):
    a,b=read_kit(old,SEALS[0]),read_kit(new,SEALS[1]);need(a==b,'board envelope differs');archive(reports)
    src=b['rtl/'+TOP].decode(); changed,parts=derive(src); out.mkdir()
    for name in MODS: (out/name).write_bytes(b['rtl/'+name])
    (out/TOP).write_bytes(changed.encode()); xdc=next(v.decode() for n,v in b.items() if n.endswith('.xdc')); pins=[]
    for p,(pin,_) in PADS.items():
        for prop,val in [('PACKAGE_PIN',pin),('IOSTANDARD','LVCMOS18')]:
            row=f'set_property {prop} {{{val}}} [get_ports {{{p}}}]';need(xdc.splitlines().count(row)==1,'wrong board assignment: '+p);pins.append(row)
    (out/'pads.xdc').write_bytes(('\n'.join(pins)+'\n').encode())
    for n,txt in [('stock',fixture(src,parts,False)),('typed',fixture(changed,parts,True))]: (out/(n+'.sv')).write_bytes(txt.encode())
    public=dict(scope='Ten active digital pads only; archived routed evidence is for the original BOOM. The candidate is not integrated.',
                source_seals=list(SEALS), original_pre_physopt_checkpoint_sha256='d0ead1ae8498f90d6ec268dc12c7f26d745448bcf2c20b4ce681a4dd356ef581',archived_report_sha256=RPT,
                input_sha256={Path(k).name:h(v) for k,v in a.items()},derived_sha256={n:h((out/n).read_bytes()) for n in (TOP,'stock.sv','typed.sv','pads.xdc')},
                archived_rpbf_ports=sorted(PADS),archived_hpdr_ports=sorted(OUTPUTS),input_package_pins={p:PADS[p][0] for p in INPUTS},output_package_pins={p:PADS[p][0] for p in OUTPUTS})
    (out/'inputs.json').write_bytes((json.dumps(public,indent=2)+'\n').encode());return public


INPUT_SEAL='817c093bea76891ce5e132327a4ee9d0571d937afd2ae6e9123740f9dd3b8558'


def check(inputs):
    raw=(inputs/'inputs.json').read_bytes(); need(h(raw)==INPUT_SEAL,'wrong fixture manifest')
    fields=json.loads(raw)
    for name, digest in {**fields['derived_sha256'], **{n:fields['input_sha256'][n] for n in MODS}}.items():
        need(h((inputs/name).read_bytes())==digest,'changed fixture input: '+name)
    return 'PAD_INPUTS_VERIFIED'


def sim(inputs,tools,out):
    check(inputs)
    out.mkdir(); stock=(inputs/'stock.sv').read_text(); typed=(inputs/'typed.sv').read_text()
    # A real mapping error drives SPI chip select with MOSI instead of the CS signal.
    bad=typed.replace('assign sdio_spi_dat_3 = _chiptop0_spi_0_cs_0;', 'assign sdio_spi_dat_3 = _chiptop0_spi_0_dq_0_o;');need(bad!=typed,'negative did not mutate')
    for i,src in enumerate((stock,typed,bad)):(out/f'dut{i}.sv').write_text(src.replace('module io_fixture(',f'module dut{i}('))
    tb=['module tb; reg clk; reg [4:0] ext, drive; integer i,j,n,neg; ']
    for v in range(3):
        tb.append(f'wire [4:0] i{v}=ext; wire [4:0] o{v}, s{v};')
        ports=[f'.{p}(i{v}[{i}])' for i,p in enumerate(INPUTS)]+[f'.{p}(o{v}[{i}])' for i,p in enumerate(OUTPUTS)]
        tb.append(f'dut{v} u{v}('+', '.join(ports+[f'.clk(clk), .drive(drive), .sample(s{v})'])+');')
    tb+=['task tick; begin #2; clk=1; #2; if (o0!==drive || o1!==drive || s0!==ext || s1!==ext || i0!==ext || i1!==ext) $fatal(1,"pad mismatch %d",n); if(o2!==drive) neg=neg+1; clk=0; #1; n=n+1; end endtask',
         'initial begin clk=0; n=0; neg=0; for(i=0;i<1024;i=i+1) begin {drive,ext}=i[9:0]; tick; end',
         "for(j=0;j<5;j=j+1) begin ext=0; drive=31; ext[j]=1'bz; tick; ext[j]=1'bx; tick; drive[j]=1'bx; tick; drive[j]=1'bz; tick; end",
         'if(n!=1044 || neg<512) $fatal(1,"coverage"); $display("PAD_COMPARE samples=%0d negative=%0d",n,neg); $finish; end endmodule']
    (out/'tb.sv').write_text('\n'.join(tb)+'\n')
    def run(cmd,args):
        exe=tools/'bin'/(cmd+('.bat' if os.name=='nt' else '')); proc=subprocess.run([str(exe),*args],cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
        (out/(cmd+'.log.txt')).write_bytes(proc.stdout);txt=proc.stdout.decode(errors='replace');need(proc.returncode==0 and not re.search(r'(?im)^\s*(?:ERROR|FATAL):',txt),cmd+' failed');return txt
    run('xvlog',['--sv',*[str(inputs/n) for n in MODS],*[f'dut{i}.sv' for i in range(3)],'tb.sv'])
    el=run('xelab',['tb','--mt','off','--timescale','1ns/1ps','-s','padpair']);need('Vivado Simulator v2024.2' in el and 'Built simulation snapshot padpair' in el,'wrong snapshot')
    log=run('xsim',['padpair','--runall']); hits=re.findall(r'^PAD_COMPARE samples=1044 negative=(\d+)\s*$',log,re.M);need(len(hits)==1 and '$finish called' in log and int(hits[0])>=512,'simulation incomplete')
    result=dict(samples=1044,all_binary_combinations=1024,extra_x_or_z_samples=20,wrong_spi_select_disagreements=int(hits[0]),testbench_sha256=h((out/'tb.sv').read_bytes()),fixture_inputs_sha256=h((inputs/'inputs.json').read_bytes()))
    (out/'sim.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); subs=p.add_subparsers(dest='action',required=True)
    for action,args in [('prepare',('old','new','reports','out')),('sim',('inputs','tools','out')),('check',('inputs',))]:
        sub=subs.add_parser(action)
        for arg in args:sub.add_argument(arg,type=Path)
    ns=vars(p.parse_args());fn={'prepare':prepare,'sim':sim,'check':check}[ns.pop('action')];print(json.dumps(fn(**{k:v.resolve() for k,v in ns.items()}),indent=2))
