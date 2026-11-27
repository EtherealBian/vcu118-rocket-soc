#!/usr/bin/env python3
"""Cross-check selected clock directions in one Vivado run. Never grants signoff."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path
import re
import runpy
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from routed_replay import CDC, compare_reports, portable, section, signature

XDC = runpy.run_path(str(HERE / 'review-mega-checkpoint-xdc.py'))
PATHS = runpy.run_path(str(HERE / 'review-mega-routed-paths.py'))
CPU, UI, TCK = 'clk_out1_harnessSysPLL', 'mmcm_clkout0', 'JTCK'
CLOCKS = (CPU, UI, TCK)
COMMAND = ('set_clock_groups -asynchronous -group [get_clocks -of_objects [get_pins '
           'mig/island/blackbox/c0_ddr4_ui_clk]] -group [get_clocks -of_objects '
           '[get_pins harnessSysPLL/clk_out1]] -group [get_clocks JTCK]')
REPORTS = ('clock-interaction.rpt', 'full-timing.rpt', 'cdc.rpt', 'routed-clocks.rpt')
CONTROLS = {'split5h-impl-a': '50b2c5aec7e1ba1d231e03fce87c218bc525bb8f0933a244d621778718fbf868',
            'perf-boom5i-impl-a': 'ea8ec7940bcd7995ae4cedd9b1129b834f581c5753d3c681d49ba5267673040a'}


def require(ok, why):
    if not ok:
        raise ValueError(why)


def check_groups(obj, ident):
    files, _ = XDC['read'](obj / 'post_opt.dcp', ident)
    groups = [(kind, line) for kind, (lines, _) in files.items() for line in lines if line.startswith('set_clock_groups ')]
    require(groups == [('XDC', COMMAND)], 'unexpected asynchronous group declaration')


def declaration(obj):
    ident = XDC['INPUTS'][1]
    check_groups(obj, ident)
    return {'stage': 'four-wide post-opt declaration only', 'post_opt_sha256': ident[0], 'xdc_command': COMMAND}


def interactions(text, path):
    split = re.split(r'^-{20,}[ \t]*\n', text, maxsplit=2, flags=re.M)
    require(len(split) == 3, 'invalid clock interaction header')
    _, header, body = split
    for field, expected in [('Design State', 'Physopt postRoute'), ('Design', XDC['TOP']), ('Device', 'xcvu9p-flga2104')]:
        require(re.findall(r'^\| '+field+r'\s*:\s*(.+?)\s*$', header, re.M) == [expected], 'foreign '+field)
    cmds = re.findall(r'^\| Command\s*:\s*report_clock_interaction -file (.+?)\s*$', header, re.M)
    require(len(cmds) == 1 and portable(cmds[0]) == portable(path.resolve()) and
            len(re.findall(r'^\| Tool Version\s*:\s*Vivado v\.2024\.2 ', header, re.M)) == 1, 'foreign report path/tool')
    head, = re.findall(r'^From Clock .+$', body, re.M)
    lines = body.split(head+'\n')[1].splitlines()
    spans = [m.span() for m in re.finditer(r'-+', lines[0])]
    names = [head[a:b].strip() for a,b in spans]
    require(names == ['From Clock','To Clock','Clock Edges','WNS(ns)','TNS(ns)','Endpoints','Endpoints','Requirement(ns)','Classification','Constraints'], 'invalid interaction columns')
    result = {}
    for line in filter(str.strip, lines[1:]):
        row = [line[a:b].strip() for a,b in spans]
        require(not any(line[b:c].strip() for (_,b),(c,_) in zip(spans,spans[1:])) and not line[spans[-1][1]:].strip(), 'overflow in interaction table')
        src,dst,edges,wns,tns,bad,total,req,cls,exc = row
        require(src and dst and (src,dst) not in result and cls and exc and 0 <= int(bad) <= int(total), 'invalid/duplicate interaction')
        require(all([edges,wns,tns,req]) or not any([edges,wns,tns,req]), 'partly empty interaction setup record')
        result[src,dst] = (cls,exc,int(total),Decimal(wns) if wns else None)
    return result


def timing_tables(text):
    setup, ignored = defaultdict(list), set()
    titles = ['Intra Clock Table','Inter Clock Table','Other Path Groups Table','User Ignored Path Table','Unconstrained Path Table']
    for idx, title in enumerate(titles[:-1]):
        lines = section(text,title,titles[idx+1]).splitlines()
        i, = [i for i,l in enumerate(lines) if l.startswith(('Clock ', 'From Clock ', 'Path Group '))]
        head = lines[i]; seen = set()
        for line in lines[i+2:]:
            if not line.strip() or set(line.strip()) == {'-'}: continue
            if idx == 3:
                a,b = head.index('From Clock'),head.index('To Clock'); key = (line[a:b].strip(),line[b:].strip())
                ignored.add(key); continue
            # Vivado right-aligns numeric values to the END of each column heading.
            ws = head.index('WNS(ns)')+7; ns = head.index('TNS Total Endpoints')+19
            lead = line[:ws].split(); n = (1,2,3)[idx]; require(len(lead) in (n,n+1), 'invalid timing group/clock names')
            key = (lead[0],lead[0]) if idx == 0 else tuple(lead[n-2:n]); unique = tuple(lead[:n])
            require(unique not in seen, 'duplicate timing group'); seen.add(unique)
            nums = lead[n:] + line[ws:ns].split()
            if nums:
                require(len(nums)==4 and all(re.fullmatch(r'-?\d+\.\d{3}', x) for x in nums[:2]) and
                        0 <= int(nums[2]) <= int(nums[3]) and int(nums[3]) > 0, 'invalid setup tuple')
                setup[key].append((Decimal(nums[0]), int(nums[3])))
    return setup, ignored


def crossings(text):
    total = CDC['inventory'](text)['total_rows']; out = defaultdict(Counter)
    src = dst = None
    for line in text.splitlines():
        if line.startswith('Source Clock: '): src,dst = line[14:],None
        elif line.startswith('Destination Clock: '): dst = line[19:]
        elif re.match(r'^\s*\d+\s+CDC-',line):
            _,rule,sev,_,_,exc,_,_ = re.split(r'\s{2,}',line.strip()); out[src,dst][(sev,rule,exc)] += 1
    require(sum(sum(v.values()) for v in out.values())==total, 'CDC count mismatch')
    return out


def join(inter, setup, ignored, cdc):
    rows = []
    for pair in permutations(CLOCKS,2):
        data = cdc.get(pair, {}); row = {'from':pair[0], 'to':pair[1]}
        if pair not in inter:
            require(CPU not in pair and not data and pair not in ignored and not setup.get(pair), 'missing expected or reported clock pair')
            row['scope'] = 'pair not reported (not a safety conclusion)'
        else:
            cls,exc,ep,w = inter[pair]
            require((cls,exc,w)==('Ignored','Asynchronous Groups',None) and pair in ignored and not setup.get(pair), 'unexpected STA coverage for grouped pair')
            require(data and all(k[2]=='Asynch Clock Groups' for k in data), 'missing or mixed CDC group exception')
            row.update(scope='group-excluded from ordinary setup',interaction_endpoints=ep,cdc_rule_counts={f'{s} {r}':v for (s,r,_),v in sorted(data.items())})
        rows.append(row)
    cases = []
    for a,b,cls,exc,has_ignored in [(CPU,CPU,'Clean','Timed',False),(UI,'mmcm_clkout5','Ignored','Max Delay Datapath Only',True),('sys_clock','sys_clock','Clean','Partial False Path',True)]:
        k = (a,b); c,e,ep,w = inter[k]; timed = setup.get(k)
        # Unknown or changed classification needs review; a negative numeric WNS
        # by itself is not a parsing error and must not be hidden.
        require(e==exc and c==cls and timed and w is not None and (k in ignored)==has_ignored, 'unexpected timed control scope')
        require(abs(min(r[0] for r in timed)-w)<=Decimal('.005'), 'setup slack mismatch across reports')
        cases.append(dict(source=a,destination=b,classification=c,constraint=e,interaction_endpoints=ep,setup_endpoints_by_group=[v for _,v in timed],setup_wns_ns=str(min(r[0] for r in timed)),also_user_ignored=has_ignored))
    return dict(group_directions=rows,timed_controls=cases,cdc_only=[dict(source=a,destination=b,rows=sum(v.values())) for (a,b),v in sorted(cdc.items()) if (a,b) not in inter])


def bundle(obj):
    folder=obj/'report'; raw={n:(folder/n).read_bytes() for n in REPORTS}
    ids={n:PATHS['synth'].digest(obj/n) for n in ('post_opt.dcp','post_route.dcp')}
    ids.update({'report/'+n:sha256(v).hexdigest() for n,v in raw.items()})
    return folder,raw,ids


def matrix(folder,raw):
    for n in REPORTS[1:]: signature(n,raw[n],folder/n)
    inter,timing,cdc,clocks=[raw[n].decode().replace('\r\n','\n') for n in REPORTS]
    for clock in CLOCKS:
        require(len(re.findall(r'^'+re.escape(clock)+r'\s+\d+\.\d+\s+\{[\d.]+ [\d.]+\}\s+\S+\s+\{[^}]+\}\s*$',clocks,re.M))==1, 'clock missing from routed inventory')
    return join(interactions(inter,folder/REPORTS[0]),*timing_tables(timing),crossings(cdc))


def historical(artifacts):
    out = {'scope':'Historical controls and four-wide post-opt declaration only; no four-wide routed results or board authorization.',
           'current':declaration(artifacts/'perf-mega175-split-impl-d'/'obj'), 'historical_controls':{}}
    for run,wanted in CONTROLS.items():
        folder,raw,ids = bundle(artifacts/run/'obj')
        require(sha256(json.dumps(ids,sort_keys=True,separators=(',',':')).encode()).hexdigest()==wanted, 'changed historical input bundle')
        check_groups(folder.parent, (ids['post_opt.dcp'],run,'<kit>','<cfg>'))
        out['historical_controls'][run]=dict(sha256=ids,**matrix(folder,raw))
    return out


def routed(run,kit,log,extra):
    obj=run/'obj'; decl=declaration(obj); anchor=PATHS['mega'](run,kit,log)
    folder,raw,ids=bundle(obj); replay=json.loads((extra/'replay.json').read_bytes())
    check=compare_reports(folder,extra/'routed'/'replay')
    require(anchor['post_route_dcp_sha256']==ids['post_route.dcp']==replay['post_route_dcp_sha256'] and
            check==replay['reports'] and all(r['matches'] for r in check.values()) and
            all(check[n]['original']['sha256']==ids['report/'+n] for n in REPORTS[1:]), 'DCP/replay identity mismatch')
    return dict(scope='Original clock interaction checked against reopened-report evidence. Selected directions only; not signoff.',post_opt=decl,input_seal=anchor['board_input_seal'],sha256=ids,**matrix(folder,raw))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='mode',required=True)
    sub.add_parser('controls').add_argument('artifacts',type=Path)
    r=sub.add_parser('routed')
    for name in ('run','kit','log','extra'): r.add_argument(name,type=Path)
    a=p.parse_args(); result=historical(a.artifacts) if a.mode=='controls' else routed(a.run,a.kit,a.log,a.extra)
    print(json.dumps(result,indent=2))
