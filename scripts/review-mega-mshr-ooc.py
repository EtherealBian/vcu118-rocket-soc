#!/usr/bin/env python3
"""Review optimized or routed OOC checkpoints against the SAT-certified boundaries."""
import argparse
import csv
from datetime import datetime
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
PREP = runpy.run_path(str(HERE / 'prepare-mega-mshr-ooc.py'))
common = runpy.run_path(str(HERE / 'review-mega-loop-ooc.py'))
need, single = common['need'], common['single']
DRIVER = HERE / 'implement-mega-mshr-ooc.tcl'
PART = 'xcvu9p-flga2104-2L-e'
PAT = {'all':r'q_\w+', 'branch':r'q_dc_io_lsu_brupdate_b1_mispredict_mask',
       'address1':r'q_dc_s2_req_1_addr', 'state':r'q_m[0-7]_state',
       'rpq':r'q_q[0-7]_(?:enq_ptr_value|deq_ptr_value|maybe_full)'}
FILTER={'branch':'q_dc_io_lsu_brupdate_b1_mispredict_mask_reg*', 'address1':'q_dc_s2_req_1_addr_reg*',
        'state':'q_m?_state_reg*','rpq':'q_q?_*_reg*'}
WANT = {('all',i) for i in range(3)} | {(g,2) for g in PAT if g!='all'}
N = r'(-?\d+\.\d+)'


def h(p):
    with p.open('rb') as f:
        s=sha256()
        for block in iter(lambda:f.read(1<<20), b''): s.update(block)
        return s.hexdigest()


def stamp(s):
    return datetime.strptime(' '.join(s.split()),'%a %b %d %H:%M:%S %Y')


def check_header(text, name, cmd, device, state):
    for field, value in [('Design','boundary'),('Design State',state),('Device',device)]:
        need(single(r'^\| '+field+r'\s*:\s*(\S+)\s*$', text)==value,'wrong '+field+' in '+name)
    need('Vivado v.2024.2 (win64) Build 5239630' in text,'wrong Vivado release')
    actual=single(r'^\| Command\s*:\s*(.+)$',text).strip()
    need(actual.startswith(cmd+' ') and actual.endswith(' -file '+name),'wrong report command '+name)


def path(row, text, name, state):
    g,i=row['group'],int(row['output']); start,end=row['from'],row['to']
    need((g,i) in WANT and end==f'result_reg[{i}]/D' and re.fullmatch(PAT[g]+r'_reg(?:\[\d+\])?/C',start),'wrong capture or launch group')
    check_header(text,name,'report_timing -of_objects','xcvu9p-flga2104',state)
    source='[all_registers -clock [get_clocks cpu]]' if g=='all' else '[get_cells -hierarchical -quiet -filter {IS_SEQUENTIAL == 1 && NAME =~ '+FILTER[g]+'}]'
    want='report_timing -of_objects [get_timing_paths -quiet -from '+source+' -to [get_pins {'+end+'}] -delay_type max -max_paths 1] -input_pins -file '+name
    need(single(r'^\| Command\s*:\s*(.+)$',text).strip()==want, 'wrong query for '+name)
    need(re.findall(r'^  (?:Source|Destination):\s+(\S+)\n[^\n]+clocked by cpu  \{rise@0.000ns fall@2.857ns period=5.714ns\}',text,re.M)==[start,end], 'path/table mismatch')
    need(single(r'^  Path Group:\s+(\S+)',text)=='cpu' and single(r'^  Path Type:\s+(\w+)',text)=='Setup' and single(r'^  Requirement:\s+'+N+'ns',text)=='5.714','not same setup path group')
    met,slack=single(r'^Slack \((MET|VIOLATED)\)\s*:\s*'+N+'ns',text)
    data,logic,route=single(r'^  Data Path Delay:\s+'+N+r'ns\s+\(logic '+N+r'ns \([\d.]+%\)\s+route '+N+r'ns \([\d.]+%\)\)',text)
    levels=single(r'^  Logic Levels:\s+(\d+)',text)
    need((D(slack)<0)==(met=='VIOLATED') and D(slack)==D(row['slack_ns']) and D(data)==D(row['data_ns']) and levels==row['levels'] and abs(D(data)-D(logic)-D(route))<=D('.002'),'inconsistent path measurements')
    return dict(start=start,end=end,slack_ns=slack,data_ns=data,logic_ns=logic,route_ns=route,levels=int(levels))


def review(inp, group, case, opt_only):
    d=group/case; log_path=group/(case+'-driver')/'vivado.log';log=log_path.read_text(errors='replace').replace('\\','/')
    cmd=single(r'^# Command line\s+: (.*)$',log)
    need(cmd.endswith(' -source '+DRIVER.as_posix()+' -tclargs '+inp.as_posix()+' '+d.as_posix()+' '+case+(' opt-only' if opt_only else '')),'wrong build/driver')
    for module,src in [('boundary','boundary.v'),('top',case+'.v'),('mshr_cut',case+'.v'),('resp_cut',case+'.v')]:
        need(re.search(r"^INFO: \[Synth 8-6157\] synthesizing module '"+module+r"' \["+re.escape((inp/src).as_posix())+r':\d+\]$',log,re.M),'missing source '+module)
    dcp=d/('local-opt.dcp' if opt_only else 'local-routed.dcp'); mark="INFO: [Common 17-1381] The checkpoint '"+dcp.as_posix()+"' has been generated."
    def ordered(rows):
        pos=-1; ls=log.splitlines()
        for v in rows:
            need(ls.count(v)==1 and ls.index(v)>pos,'missing/reordered stage: '+v);pos=ls.index(v)
    place=['Command: place_design','Command: route_design']; lines=log.splitlines()
    if opt_only: need(not any(v in lines for v in place),'optimized-only logs contain physical stages')
    ordered([f'Command: synth_design -mode out_of_context -top boundary -part {PART}','Command: opt_design',*([] if opt_only else place),mark,('MSHR_OOC_OPT_ONLY_NOT_ROUTED ' if opt_only else 'MSHR_REGISTERED_OOC_COLLECTED ')+case]);need(not re.search(r'^ERROR:',log,re.M),'Vivado reported error')
    begin=stamp(single(r'^# Start of session at:\s+(.+)$',log));end=stamp(single(r'^INFO: \[Common 17-206\] Exiting Vivado at (.+)\.\.\.$',log))
    def native(n):
        t=(d/n).read_text();need(begin<=stamp(single(r'^\| Date\s*:\s*(.+)$',t))<=end,'foreign report timestamp: '+n);return t
    with ZipFile(dcp) as z:
        doc=ET.fromstring(z.read('dcp.xml'))
        for k,v in [('Top','boundary'),('OutOfContext','1'),('Part',PART),('BUILD_NUMBER','5239630')]:
            need([t.get('Name') for t in doc.findall(k)]==[v],'wrong checkpoint '+k)
        if not opt_only: need([t.get('Name') for t in doc.findall('File') if t.get('Type')=='PHYSDB_ROUTE']==['boundary.rdb'],'not a routed checkpoint')
    names=['timing.rpt','util.rpt','paths.tsv'];timing,util=[native(n) for n in names[:2]]
    state='Optimized' if opt_only else 'Routed'
    check_header(timing,'timing.rpt','report_timing_summary','xcvu9p-flga2104',state);check_header(util,'util.rpt','report_utilization',PART,state)
    if not opt_only:
        names.append('route.rpt');route=(d/'route.rpt').read_text()
        nets=[int(single(r'# of '+k+r'\.+\s*:\s*(\d+)\s*:',route)) for k in ('routable nets','fully routed nets','nets with routing errors')]
        need(nets[0]==nets[1]>0 and nets[2]==0,'partially routed')
    need(re.search(r'^cpu\s+\{0\.000 2\.857\}\s+5\.714\s+',timing,re.M),'wrong clock')
    sta=single(r'^cpu\s+(-?[\d.]+(?:\s+-?[\d.]+){11})\s*$',timing).split()
    with (d/'paths.tsv').open(newline='') as f:
        reader=csv.DictReader(f,delimiter='\t');rows=list(reader);need(reader.fieldnames==['group','output','slack_ns','data_ns','levels','from','to'],'wrong table')
    keys=[(r['group'],int(r['output'])) for r in rows];need(set(keys)==WANT and len(keys)==len(WANT),'incomplete path sampling')
    obs={}
    for (g,i),r in zip(keys,rows):
        n=f'path-{g}-{i}.rpt';names.append(n);obs[f'{g}-{i}']=path(r,native(n),n,state)
    need(min(D(obs[f'all-{i}']['slack_ns']) for i in range(3))==D(sta[0]) and int(sta[3])==int(sta[7])==3,'unaccounted register-to-register endpoints')
    u=util.split('1.1 Summary of Registers by Type\n---',1)[0]
    if opt_only:
        obs={k:{f:v for f,v in data.items() if f in ('start','end','levels')} for k,data in obs.items()}
    fields={} if opt_only else dict(setup_wns_ns=sta[0],hold_whs_ns=sta[4],pulse_wpws_ns=sta[8],fully_routed_nets=nets[1],setup_failing_endpoints=int(sta[2]))
    return dict(**fields,design_state=state,register_setup_endpoints=int(sta[3]),
                luts=int(single(r'^\| CLB LUTs\*?\s*\|\s*(\d+)\s*\|.*$',u)),registers=int(single(r'^\| CLB Registers\s*\|\s*(\d+)\s*\|.*$',u)),paths=obs,
                log_sha256=h(log_path),checkpoint_sha256=h(dcp),report_sha256={n:h(d/n) for n in names})


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('archive','prepared','runs'):ap.add_argument(n,type=lambda s:Path(s).resolve(strict=True))
    ap.add_argument('cases',nargs='+',choices=PREP['CASES'])
    ap.add_argument('--opt-only',action='store_true',help='require pre-placement checkpoints; omit estimated delay/slack')
    a=ap.parse_args();need(len(set(a.cases))==len(a.cases),'duplicate case')
    with tempfile.TemporaryDirectory() as tmp:bound=PREP['make'](a.archive,Path(tmp)/'input')
    need(json.loads((a.prepared/'bound.json').read_bytes())==bound and all(h(a.prepared/n)==v for n,v in bound['files_sha256'].items()),'physical inputs differ from regenerated verified cuts')
    result={k:review(a.prepared,a.runs,k,a.opt_only) for k in a.cases}
    print(json.dumps(dict(scope=('Pre-placement only. Inspected logic levels on estimated worst paths; no routed measurements.' if a.opt_only else 'One isolated placement/route per case.')+' Registered MSHR/response/LSU cut, not whole-SoC timing, a CPU pipeline change or a board score.',period_ns='5.714',inputs=bound['files_sha256'],driver_sha256=h(DRIVER),cases=result),indent=2))
