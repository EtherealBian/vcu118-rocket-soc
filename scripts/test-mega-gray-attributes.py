#!/usr/bin/env python3
"""Bind the isolated AXI crossing test to both sealed BOOM kits and archived CDC rows."""
import argparse
import csv
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import tempfile

HERE=Path(__file__).resolve().parent
S,D='AXI4AsyncCrossingSource','AXI4AsyncCrossingSink'
M,I='XilinxVCU118MIG','XilinxVCU118MIGIsland'
KITS=runpy.run_path(str(HERE/'test-mega-aw-reset.py'))['SEALS']
CHK=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']
PART='xcvu9p-flga2104-2L-e'; CH=('aw','w','b','ar','r')

def need(q,msg):
    if not q: raise ValueError(msg)

def h(b): return sha256(b).hexdigest()
def asc(p): return re.sub(r'//[^\n]*','',p.read_text())

def pins(src,kind,inst):
    a=re.findall(r'^  '+kind+' '+inst+r' \((.*?)^  \);',src,re.M|re.S);need(len(a)==1,'missing instance '+inst)
    return dict(re.findall(r'^    \.(\w+)\s+\((\w+)\),?\s*$',a[0],re.M))

def ports(src):
    b=src.split(');',1)[0]; p=re.findall(r'^  (input|output)\s+(\[\d+:0\]\s+)?(\w+)\s*,?\s*$',b,re.M)
    need(len(p)==len(set(n for _,_,n in p))==len(re.findall(r'^  (?:input|output)\b',b,re.M)),'unsupported port');return {n:(io,w.strip()) for io,w,n in p}

def fixture(text):
    pa,pb=ports(text[S]),ports(text[D]); sa={k[9:]:v for k,v in pa.items() if k.startswith('auto_out_')}; sb={k[8:]:v for k,v in pb.items() if k.startswith('auto_in_')}
    a,b,c=pins(text[M],S,'axi4asource'),pins(text[M],I,'island'),pins(text[I],D,'axi4asink')
    need(len(sa)==246 and sa.keys()==sb.keys(),'async port inventory'); seen=set()
    for key,(io,w) in sa.items():
        u='auto_out_'+key; v='auto_axi4in_xing_in_'+key; z='auto_in_'+key
        need(io!=sb[key][0] and w==sb[key][1] and a[u]==b[v] and c[z]==v and a[u] not in seen,'async pin direction/width/wire '+key);seen.add(a[u])
    decl=[]; inst=[]; wires=[]
    for ix,(name,ps,ip,inner,outer,clk,rst) in enumerate([(S,pa,'axi4asource','auto_out_','auto_in_','sys','sr'),(D,pb,'axi4asink','auto_in_','auto_out_','ui','ur')]):
        con=[]
        for n,(io,w) in ps.items():
            if n.startswith(inner):
                target='link_'+n[len(inner):]
                if not ix: wires.append('wire '+w+' '+target+';')
            else:
                if n in ('clock','reset'): target={'clock':clk,'reset':rst}[n]
                else: need(n.startswith(outer),'unexpected external port'); target=('cpu_' if not ix else 'ddr_')+n[len(outer):]
                decl.append(io+' '+w+' '+target)
            con.append('.'+n+'('+target+')')
        inst.append(name+' '+ip+' ('+', '.join(con)+');')
    return ('module vcu_gray_probe('+',\n'.join(decl)+');\n'+'\n'.join(wires+inst)+'\nendmodule\n').encode()

def read_pins(bits,cdc):
    hist=json.loads((HERE.parent/'docs/perf-mega175-gray-diagnostic.json').read_bytes()); prev=json.loads((HERE.parent/'docs/perf-mega175-dmi-reset.json').read_bytes())
    need(h(bits.read_bytes())==hist['input_sha256']['bits.tsv'] and h(cdc.read_bytes())==prev['physical_cdc_report_sha256'],'foreign archived CDC/endpoint data')
    rows=list(csv.DictReader(bits.read_text().splitlines(),delimiter='\t')); text=cdc.read_text(); need(len(rows)==40,'expected 40')
    for ch in CH:
        for ptr in ('ridx','widx'):
            for bit in range(4):
                r,=[r for r in rows if (r['channel'],r['pointer'],r['bit'])==(ch,ptr,str(bit))]; a=r['launch']+'/C'; b=r['capture']+'/D'; lines=[l.strip() for l in text.splitlines() if l.endswith(b) and a in l.split()];need(len(lines)==1 and re.match(r'^\d+\s+CDC-2\s+Warning\s+1-bit synchronized with missing ASYNC_REG property\s+3\s+Asynch Clock Groups\s+',lines[0]),'wrong original CDC row '+b)
    return rows

def check_gray_msb(text):
    # Allow binary[3] as launch only because both FF D bits and both resets are identical.
    for ch in CH:
        for side,ptr in [('Source','widx'),('Sink','ridx')]:
            name=f'AsyncQueue{side}_AXI4Bundle{ch.upper()}'; t=text[name]
            b=f'{ptr}_{ptr}_bin'; g=ptr+'_gray'; inc=ptr+'_incremented'
            need(len(re.findall(r'wire \[3:0\]\s+'+ptr+r' = \{'+inc+r'\[3\],',t))==1 and
                 t.count(f'assign io_async_{ptr} = {g};')==1,'gray output or MSB '+name)
            block,=re.findall(r'^  always @\(posedge clock or posedge reset\) begin\s+if \(reset\) begin(.*?)^    end\s+else begin(.*?)^    end\s+end\s*$',t,re.S|re.M)
            for reg,d in [(b,inc),(g,ptr)]:
                need(t.count(reg+' <=')==2 and f"{reg} <= 4'h0;" in block[0] and f'{reg} <= {d};' in block[1], 'gray storage differs '+name)

def prepare(stock,kit,bits,cdc,out,verify=False):
    need([h((x/'CANDIDATE.sha256').read_bytes()) for x in (stock,kit)]==KITS,'wrong kit pair'); old,new=CHK(stock),CHK(kit); rows=read_pins(bits,cdc)
    text={}; root=kit/'rtl'; ids={}
    def walk(n):
        if n in text:return
        k='rtl/'+n+'.sv'; p=root/(n+'.sv');need(new[k]==old[k],'reviewed module differs '+n); text[n]=asc(p);ids[n]=new[k]
        for t,_ in re.findall(r'^  (\w+) (\w+) \(',text[n],re.M):
            need((root/(t+'.sv')).is_file(),'unknown child '+t);walk(t)
    walk(S);walk(D);need(len(text)==20,'unexpected closure'); closure=sorted(text)
    for n in (M,I):
        k='rtl/'+n+'.sv';need(new[k]==old[k],'board wiring changed');text[n]=asc(root/(n+'.sv'));ids[n]=new[k]
    check_gray_msb(text)
    raw=fixture(text); need(all(x!=out and x not in out.parents and out not in x.parents for x in (stock,kit)),'outputs must be disjoint')
    paths=[root/(n+'.sv') for n in closure]; pin_text='\n'.join('\t'.join([r['channel'],r['pointer'],r['bit'],r['launch'].replace('mig/axi4asource/','axi4asource/').replace('mig/island/axi4asink/','axi4asink/'),r['capture'].replace('mig/axi4asource/','axi4asource/').replace('mig/island/axi4asink/','axi4asink/')]) for r in rows)+'\n'
    if verify:
        need((out/'probe.sv').read_bytes()==raw and (out/'pins.tsv').read_text()==pin_text and
             [Path(x).resolve(strict=True) for x in (out/'sources.list').read_text().splitlines()]==paths,'test input files changed')
    else:
        need(not out.exists(),'fresh external input directory required');out.mkdir();(out/'probe.sv').write_bytes(raw)
        (out/'sources.list').write_text('\n'.join(str(p) for p in paths)+'\n');(out/'pins.tsv').write_text(pin_text)
    return dict(physical_kit_sha256=KITS,archived_cdc_sha256=h(cdc.read_bytes()),archived_pointer_map_sha256=h(bits.read_bytes()),board_wiring_and_crossing_rtl_sha256=ids,fixture_sha256=h(raw),async_fields_checked=246,synthesized_modules=len(closure),part=PART)

def table(path):
    text=path.read_text(); source=dest=None; rows={}; summary={}
    for pat in (r'^\| Tool Version +: Vivado v\.2024\.2 .*? Build 5239630 ',r'^\| Design +: vcu_gray_probe\s*$',r'^\| Device +: xcvu9p-flga2104\s*$',r'^\| Design State +: Synthesized\s*$'):
        need(re.search(pat,text,re.M),'wrong design or Vivado in '+path.name+' '+pat)
    cmd,=re.findall(r'^\| Command +: report_cdc -details -file (.+?)\s*$',text,re.M)
    need(Path(cmd).resolve()==path.resolve(),'report not from this invocation: '+path.name)
    for line in text.splitlines():
        if line.startswith('Source Clock: '):source=line.partition(': ')[2];dest=None
        elif line.startswith('Destination Clock: '):dest=line.partition(': ')[2]
        elif re.match(r'^CDC-\d+\s',line):
            k,sev,count,_=line.split(None,3);need(k not in summary,'duplicate summary');summary[k]=(sev,int(count))
        elif re.match(r'^\s*\d+\s+CDC-',line):
            f=line.split();need({source,dest}=={'sys','ui'},'unexpected clock pair');key=(source,dest,f[-2],f[-1]);need(key not in rows,'duplicate CDC pair');rows[key]=(f[1],f[2],' '.join(f[3:-2]))
    need(rows and Counter(row[0] for row in rows.values())==Counter({k:n for k,(_,n) in summary.items()}),'detail rows do not account for summary counts');return rows,summary


def review(inp,out,inputs):
    need(json.loads((inp/'inputs.json').read_bytes())==inputs,'prepared input receipt differs');rows=[line.split('\t') for line in (inp/'pins.tsv').read_text().splitlines()]; stages={}; others=None; rule_base='1-bit synchronized with missing ASYNC_REG property';rule_tag='1-bit synchronized with ASYNC_REG property'
    receipt=['actual.tsv','baseline.rpt','candidate.rpt','omitted-one-bit.rpt']
    need((out/'completed.txt').read_text().splitlines()==[f'{n} {(out/n).stat().st_size}' for n in receipt]+['VCU_GRAY_ATTR_EXPERIMENT_FINISHED_NOT_SIGNOFF'],'no matching completed native experiment')
    actual=[line.split('\t') for line in (out/'actual.tsv').read_text().splitlines()]
    need(len(actual)==len(rows)==40 and rows[0][:3]==['aw','widx','0'],'incorrect native map length or omission identity')
    aliases=[]
    for spec,observed in zip(rows,actual):
        ch,ptr,bit,orig,launch,capture=observed
        need([ch,ptr,bit,orig,capture]==spec,'archived and actual map disagree')
        if orig!=launch:
            need(bit=='3' and orig.endswith(f'/{ptr}_gray_reg[3]') and launch==orig.rsplit('/',1)[0]+f'/{ptr}_{ptr}_bin_reg[3]','unproved launch substitution')
            aliases.append(f'{ch}:{ptr}:{bit}')
    need(len({r[4] for r in actual})==len({r[5] for r in actual})==40,'duplicate actual endpoint')
    for run,name in enumerate(('baseline','candidate','omitted-one-bit')):
        path=out/(name+'.rpt'); all_rows,summary=table(path); count=Counter(); remain=dict(all_rows)
        for i,(ch,ptr,bit,_,a,b) in enumerate(actual):
            syswrite=(ch in ('aw','ar','w'))==(ptr=='widx');sc,dc=('sys','ui') if syswrite else ('ui','sys');key=(sc,dc,a+'/C',b+'/D');tagged=bool(run) and not (run==2 and not i);want=(('CDC-3','Info',rule_tag) if tagged else ('CDC-2','Warning',rule_base));expected=(*want[:2],want[2]+' 3 Asynch Clock Groups');need(remain.pop(key,None)==expected,'wrong exact CDC crossing '+name+': '+str(key));count[want[0]]+=1
        if others is None:others=remain
        need(others==remain,'non-target CDC endpoint or rule changed');stages[name]=dict(target_rules=dict(sorted(count.items())),all_classified_rows=len(all_rows),report_sha256=h(path.read_bytes()))
    return dict(native_endpoint_map_sha256=h((out/'actual.tsv').read_bytes()),equivalent_binary_msb_launches=aliases,
                scripts_sha256_lf={p.name:h(p.read_text().replace('\r\n','\n').encode()) for p in (Path(__file__),HERE/'probe-mega-gray-attributes.tcl',HERE/'annotate-mega-gray-pointers.tcl')},scope='Vivado post-synthesis OOC experiment on the real 5-channel CPU/MIG AXI crossing. Same live netlist, same clocks; change only receiver FF attributes. No placement, route, MTBF, full-system CDC closure or board result.',inputs=inputs,receiver_FFs_checked=120,unique_launch_FFs_checked=40,interstage_links_checked_for_exclusive_fanout=80,other_report_rows_unchanged=len(others),other_rules=dict(sorted(Counter(x[0] for x in others.values()).items())),negative_control=dict(channel=rows[0][0],pointer=rows[0][1],bit=int(rows[0][2])),stages=stages)


def negative_controls(inp,out,inputs):
    """Reissue the local scratch receipt, so tests must fail on data, not path or size."""
    names=('baseline.rpt','candidate.rpt','omitted-one-bit.rpt'); results=[]
    for fault,reason in [('reverse pointer order','archived and actual map disagree'),
                         ('alias lower bit','unproved launch substitution'),
                         ('swap native stages','wrong exact CDC crossing'),
                         ('drop non-target row','detail rows do not account'),
                         ('change non-target endpoint','non-target CDC endpoint or rule changed')]:
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp); actual=(out/'actual.tsv').read_text().splitlines()
            if fault=='reverse pointer order':actual[0],actual[1]=actual[1],actual[0]
            if fault=='alias lower bit':
                cols=actual[0].split('\t');cols[4]=cols[4].replace('widx_gray_reg','widx_widx_bin_reg');actual[0]='\t'.join(cols)
            (dest/'actual.tsv').write_text('\n'.join(actual)+'\n')
            for name in names:
                source=(dict(zip(names,names[1::-1])).get(name,name) if fault=='swap native stages' else name)
                text=(out/source).read_text();text=re.sub(r'^\| Command +: report_cdc -details -file .+$',lambda _: '| Command : report_cdc -details -file '+(dest/name).as_posix(),text,flags=re.M)
                if name==names[1] and fault in ('drop non-target row','change non-target endpoint'):
                    text,n=re.subn(r'^\s*\d+ +CDC-15 [^\n]+$',lambda m:'' if fault.startswith('drop') else m[0]+'_foreign',text,count=1,flags=re.M);need(n==1,'no row for negative control')
                (dest/name).write_text(text)
            (dest/'completed.txt').write_text('\n'.join(f'{n} {(dest/n).stat().st_size}' for n in ('actual.tsv',*names))+'\nVCU_GRAY_ATTR_EXPERIMENT_FINISHED_NOT_SIGNOFF\n')
            try:review(inp,dest,inputs)
            except ValueError as e:
                need(reason in str(e),'unexpected rejection for '+fault+': '+str(e));results.append(fault)
            else:raise ValueError('accepted corruption: '+fault)
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('stock','kit','bits','cdc','inputs'):p.add_argument(key,type=Path)
    p.add_argument('--review',type=Path,help='revalidate original inputs and check all rows in three completed OOC reports');a=p.parse_args()
    r=prepare(*(getattr(a,n).resolve() for n in ('stock','kit','bits','cdc','inputs')),verify=a.review is not None)
    if a.review is None:(a.inputs/'inputs.json').write_text(json.dumps(r,indent=2)+'\n'); print('Prepared sealed five-channel crossing probe')
    else:
        data=review(a.inputs,a.review,r);data['reviewer_negative_controls_rejected']=negative_controls(a.inputs,a.review,r);print(json.dumps(data,indent=2))
