#!/usr/bin/env python3
"""Review a split-process placement / route from a published, optimized MSHR cut."""
import argparse
import json
import re
import runpy
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'review-mega-mshr-ooc.py'))
DRIVER = HERE / 'resume-mega-mshr-ooc.tcl'
REF = HERE.parent / 'docs/perf-mega175-mshr-preplace.json'
need, single, stamp, h = (M[k] for k in ('need','single','stamp','h'))


def only_steps(lines, expected):
    # Ignore Tcl's commented script echo; it contains both arms of the stage switch.
    steps = [s for s in lines if re.match(r'^Command: (?:open_checkpoint|synth_design|opt_design|place_design|route_design|phys_opt_design)(?: |$)',s)]
    need(steps == expected, 'unexpected tool command sequence')


def inspect_checkpoint(p, expected_tasks, begin, end):
    with ZipFile(p) as z:
        files = z.namelist(); need(len(files)==len(set(files)) and z.testzip() is None, 'damaged checkpoint')
        x = ET.fromstring(z.read('dcp.xml'))
        for tag,val in [('Top','boundary'),('Part',M['PART']),('BUILD_NUMBER','5239630'),('OutOfContext','1')]:
            need([t.get('Name') for t in x.findall(tag)] == [val], 'wrong checkpoint '+tag)
        types = {e.get('Type'):e.get('Name') for e in x.findall('File')}
        for t,n in [('EDIF','boundary.edf'),('JSON_RDA','boundary_rda.json'),('XDC','boundary.xdc')]:
            need(types.get(t)==n and z.getinfo(n).file_size>0,'missing checkpoint member '+n)
        xdc = z.read('boundary.xdc').decode().splitlines()
        need([s.strip() for s in xdc if s.strip() and not s.strip().startswith(('#','set_property SRC_FILE_INFO ','set_property src_info '))]==['create_clock -period 5.714 -name cpu [get_ports clk]'],'unexpected timing constraints')
        r = json.loads(z.read('boundary_rda.json')); info = r['Report Information']; tasks = r['Design QoR Summary']
        need([t['Task Name'] for t in tasks] == expected_tasks, 'wrong QoR task history')
        need(info['Design']=='boundary' and info['Device']=='xcvu9p' and info['Tool Version'].startswith('Vivado v.2024.2 (win64) Build 5239630 '), 'wrong native design')
        need(begin<=stamp(info['Date'])<=end, 'DCP outside producing session')
        # On this device even place_design can emit an RDB and a "Routed" QoR
        # header. Only executed tasks plus the native connectivity report prove route.
        for kind, member in [('PHYSDB_PLACE','boundary.pdb'),('PHYSDB_ROUTE','boundary.rdb')]:
            need(types.get(kind)==member and z.getinfo(member).file_size>0,'missing physical database '+member)
        routed = expected_tasks[-1]=='route_design'
        need(info['Design State'] in (('Routed',) if routed else ('Fully Placed','Routed')), 'wrong physical QoR state')
        return info['Design State'], [t['Task Name'] for t in tasks]


def stage(group, case, verb, src, source_sha, previous_end=None):
    noun={'place':'placed','route':'routed'}[verb]; out=group/(case+'-'+verb); run=group/(out.name+'-driver'); dest=out/('local-'+noun+'.dcp')
    log_path=run/'vivado.log'; log=log_path.read_text(errors='replace').replace('\\','/'); lines=log.splitlines(); e=json.loads((run/'exit.json').read_bytes())
    target_sha=h(dest); need(h(src)==source_sha and e['source_checkpoint_sha256']==source_sha and e['output_checkpoint_sha256']==target_sha,'checkpoint identity or chain mismatch')
    need(e['stage']==verb and e['case']==case and e['complete'] is True and e['rc']==0 and e['guard'] is None and e['driver_sha256']==h(DRIVER),'stage did not finish with this driver')
    need(single(r'^# Command line\s+: (.*)$',log)=='vivado.exe -mode batch -log vivado.log -nojournal -source '+DRIVER.as_posix()+' -tclargs '+' '.join([verb,case,src.as_posix(),out.as_posix()]), 'wrong session CLI')
    need(single(r'^# Current directory\s+: (.*)$',log)==run.as_posix() and not re.search(r'^ERROR: ',log,re.M),'wrong session or tool error')
    start='Command: open_checkpoint '+src.as_posix(); action='Command: '+verb+'_design';only_steps(lines,[start,action])
    written="INFO: [Common 17-1381] The checkpoint '"+dest.as_posix()+"' has been generated."
    marker='MSHR_RESUMED_'+noun.upper()+' '+case
    pos=[]
    for s in (start,action,written,marker):
        need(lines.count(s)==1,'missing/ambiguous '+s);pos.append(lines.index(s))
    need(pos==sorted(pos),'reordered stage')
    begin=stamp(single(r'^# Start of session at:\s+(.+)$',log)); end=stamp(single(r'^INFO: \[Common 17-206\] Exiting Vivado at (.+)\.\.\.$',log))
    need(begin<=end and (previous_end is None or previous_end<=begin),'wrong session order')
    state,tasks=inspect_checkpoint(dest,['synth_design','opt_design','place_design']+(['route_design'] if verb=='route' else []),begin,end)
    public=dict(checkpoint_sha256=target_sha,source_checkpoint_sha256=source_sha,log_sha256=h(log_path),completed_stage=verb+'_design',qor_header_state=state,qor_tasks=tasks)
    if verb=='route':
        finish=single(r'^Phase 8 Route finalize\n([\s\S]+?)^Phase 8 Route finalize \| Checksum: [a-f0-9]+$',log)
        for metric in ('Failed Nets','Unrouted Nets','Partially Routed Nets','Node Overlaps'):
            need(single(r'^  Number of '+metric+r'\s*= (\d+)$',finish)=='0','incomplete final routing: '+metric)
        need(lines.count('Routing Is Done.')==1 and single(r'^\d+ Infos?, \d+ Warnings?, (\d+) Critical Warnings? and (\d+) Errors? encountered\.$',log)==('0','0'),'routing did not finish cleanly')
        need('WARNING: [Timing 38-242] The property HD.CLK_SRC of clock port "clk" is not set.' in log,'changed local clock model')
        public['clock_boundary']='OOC clock input: HD.CLK_SRC unset, not a routed board clock tree.'
        public['measurements']=M['measurements'](out,log_path,dest,begin,end,False,input_pins=False)
        for k,path in public['measurements']['paths'].items():
            text=(out/('path-'+k+'.rpt')).read_text(); nets=re.findall(r'net \(fo=\d+, ([^)]+)\)[^\n]*?\s+(\S+)\s*$',text,re.M)
            need(len(nets)>2 and nets[0]==nets[-1]==('unset','clk') and all(kind=='routed' for kind,_ in nets[1:-1]),'missing routed data path or different clock boundary')
    return public, dest, end


def collect(pre, runs, cases, placed_only):
    ref=json.loads(REF.read_bytes()); results={}
    for case in cases:
        origin=pre/case/'local-opt.dcp'; src_sha=ref['cases'][case]['checkpoint_sha256']
        placement, placed, end=stage(runs,case,'place',origin,src_sha); entry={'place':placement}
        if not placed_only:
            entry['route']=stage(runs,case,'route',placed,placement['checkpoint_sha256'],end)[0]
        results[case]=entry
    return dict(scope='One isolated registered memory-control cut per case, not whole-chip timing, pipeline or board performance.',period_ns='5.714',preplace_record_sha256=h(REF),driver_sha256=h(DRIVER),cases=results)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('pre','runs'):ap.add_argument(n,type=lambda s:Path(s).resolve(strict=True))
    ap.add_argument('cases',nargs='+',choices=M['PREP']['CASES']);ap.add_argument('--placed-only',action='store_true'); a=ap.parse_args()
    need(len(a.cases)==len(set(a.cases)),'duplicate case'); print(json.dumps(collect(a.pre,a.runs,a.cases,a.placed_only),indent=2))
