#!/usr/bin/env python3
"""Where do the eight detailed paths from the pinned pre-physopt BOOM route diverge?"""
import argparse
import csv
from decimal import Decimal as D
from hashlib import sha256
import itertools
import json
from pathlib import Path
import re
import runpy

HERE=Path(__file__).resolve().parent
H=runpy.run_path(str(HERE/'review-mega-data-hops.py'))
CLOCK='clk_out1_harnessSysPLL'; PREFIX='chiptop0/system/tile_prci_domain/element_reset_domain_boom_tile/'


def digest(p):
    h=sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def need(x,msg):
    if not x: raise ValueError(msg)


def paths(text,rows):
    sec=re.split(r'(?m)(?=^Slack \((?:MET|VIOLATED)\)\s*:)',text)[1:]; need(len(sec)==8 and len(rows)==40,'wrong sample sizes')
    need(len({row['to'] for row in rows})==40 and all(r['destination_clock']==CLOCK and r['kind']=='max' for r in rows),'wrong endpoint table')
    slacks=[D(row['slack_ns']) for row in rows]; need(slacks==sorted(slacks),'wrong ranking')
    obs=[]
    for section,row in zip(sec,rows):
        one=lambda key:H['ROUTED']['one'](key,section)
        a=one(r'^  Source:\s+(\S+)'); b=one(r'^  Destination:\s+(\S+)'); slack=one(r'^Slack \(VIOLATED\)\s*:\s*(-[\d.]+)ns'); levels=int(one(r'^  Logic Levels:\s+(\d+)'))
        need((a,b,slack,levels)==(row['from'],row['to'],row['slack_ns'],int(row['logic_levels'])) and
             one(r'^  Path Group:\s+(\S+)')==CLOCK and one(r'^  Requirement:\s+([\d.]+)ns')=='5.714' and
             section.count('clocked by '+CLOCK+'  {rise@0.000ns fall@2.857ns period=5.714ns}')==2,'detailed path differs from endpoint table')
        data,logic,wire=one(r'^  Data Path Delay:\s+([\d.]+)ns\s+\(logic ([\d.]+)ns [^\n]*?route ([\d.]+)ns')
        hops=H['decompose'](section,dict(launch=a,capture=b,data_ns=data,logic_ns=logic,routing_ns=wire,logic_levels=levels))
        # Full arrival time column on the logic arcs (including the launch flop), not a sum of rounded rows.
        table=H['SEP'].split(section)[2]; arcs=list(H['ARC'].finditer(table)); need([arc['pin'] for arc in arcs]==[hop['driver'] for hop in hops],'cannot reconcile primitive outputs')
        start=D(arcs[0]['time'])-D(arcs[0]['delay']); at=[D(arc['time'])-start for arc in arcs]
        obs.append((a,b,hops,at,D(data)))
    return obs


def common(obs):
    groups={}
    for idx,(a,*_) in enumerate(obs): groups.setdefault(a,[]).append(idx)
    need(sorted(map(len,groups.values()))==[2,6],'not the same pair of launch families')
    result=[]
    for a,ids in groups.items():
        seq=[obs[i][2] for i in ids]
        shared=[z[0] for z in itertools.takewhile(lambda z:all(h==z[0] for h in z),zip(*seq))]; n=len(shared)
        need(n and all(len(p)>n for p in seq),'no common/diverging routed prefix')
        drivers={p[n]['driver'] for p in seq}; times={obs[i][3][n] for i in ids}
        need(len(drivers)==len(times)==1 and len({p[n]['sink'] for p in seq})>1,'not a timed common-driver fork')
        drv=drivers.pop(); t=times.pop(); nets=sum(D(h['increment_ns']) for h in shared)
        result.append(dict(launch=a[len(PREFIX):],common_routed_hops=n,common_route_sum_ns=str(nets),fork_driver=drv[len(PREFIX):],
            data_elapsed_at_driver_ns=str(t),captures=[dict(rank=i+1,pin=obs[i][1][len(PREFIX):],
                fork_fanout=obs[i][2][n]['fanout'],fork_to_first_sink_ns=obs[i][2][n]['increment_ns'],
                fork_crossings=obs[i][2][n]['slr_crossings'],remaining_data_ns=str(obs[i][4]-t)) for i in ids]))
    return result


def review(dcp,folder):
    lock=json.loads((HERE.parent/'docs/perf-mega175-routed-checkpoint.json').read_bytes())['routed_before_physopt_dcp']; hd=digest(dcp)
    need(hd==lock['sha256'] and dcp.stat().st_size==lock['bytes'],'not reviewed pre-physopt DCP')
    log=folder/'review.log'; tab=folder/'cpu-max.tsv'; rpt=folder/(CLOCK+'-max.rpt'); t=rpt.read_text(); l=log.read_text().replace('\\','/')
    launch_lines=[s for s in l.splitlines() if s.startswith('# Command line')]; args=f' -tclargs {dcp.as_posix()} {folder.as_posix()}'
    need(len(launch_lines)==1 and launch_lines[0].endswith(args) and
         f'Command: open_checkpoint {{{dcp.as_posix()}}}' in l.splitlines() and
         '\nFOUR_WIDE_PRE_PHYSOPT_CPU_REPORT_COMPLETE max\n' in l and '\nFOUR_WIDE_PRE_PHYSOPT_DIAGNOSTICS_COMPLETE_NOT_RELEASE\n' in l,'unbound archive run')
    need(bool(re.search(r'^\| Design State\s+: Routed\s*$',t,re.M)) and bool(re.search(r'^\| Design\s+: VCU118FPGATestHarness\s*$',t,re.M)) and
         bool(re.search(r'^\| Device\s+: xcvu9p-flga2104\s*$',t,re.M)) and
         f'report_timing -to [get_clocks {CLOCK}] -delay_type max -max_paths 8 -nworst 1 -input_pins -file {rpt.as_posix()}\n' in t,'unexpected scoped report')
    need(digest(tab)=='df1c4915dbf7d2aa48b17bd232709d84b17582b38ff5b3d96b92c3a4d1b7f399','foreign 40 endpoints')
    with tab.open() as f: rows=list(csv.DictReader(f,delimiter='\t'))
    r=common(paths(t,rows)); need(all(x['data_elapsed_at_driver_ns'] for x in r),'missing split')
    for bad in [t.replace(rows[0]['to'],rows[7]['to'],1),t.replace('net (fo=122, routed)','net (fo=122, missing)',1)]:
        try: paths(bad,rows)
        except ValueError: pass
        else: raise ValueError('mutated report passed')
    return dict(scope='Original routed-before-physopt CPU setup, 8 detailed paths only. Not a recovery-build timing result.',dcp_sha256=hd,
                endpoint_table_sha256=digest(tab),input_pins_report_sha256=digest(rpt),families=r,negative_controls_rejected=2)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('dcp',type=Path); p.add_argument('reports',type=Path); a=p.parse_args()
    print(json.dumps(review(a.dcp.resolve(strict=True),a.reports.resolve(strict=True)),indent=2))
