#!/usr/bin/env python3
"""Tie late placed-optimizer actions to sealed RTL and optionally routed data hops.

Reads completed phases, never opens Vivado. Exact names only: an unmatched
routed name does not prove that the original cell/net was removed or irrelevant.
"""
import argparse
import csv
import io
from collections import Counter, defaultdict
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
PLACE = runpy.run_path(str(HERE/'review-boom-placement.py'))
HOPS = runpy.run_path(str(HERE/'review-mega-data-hops.py'))
BODY_SHA = '8807881f2f58bf7eca59c44aaaaf9feac0eb88457743ff3ad5d6dc49b814c2c1'
AW = 'mig/axi4asource/nodeOut_aw_source/'
FP = 'chiptop0/system/tile_prci_domain/element_reset_domain_boom_tile/core/FpPipeline/'
NUM = r'-?\d+\.\d{3}'
EST = re.compile(r'INFO: \[Physopt 32-619\] Estimated Timing Summary \| WNS=('+NUM+r') \| TNS=('+NUM+r') \|')
MOVE = re.compile(r'INFO: \[Physopt 32-663\] Processed net (\S+)\.\s+Re-placed instance (\S+)')
BETTER = re.compile(r'INFO: \[Physopt 32-735\] Processed net (\S+)\. Optimization improves timing on the net\.')


def require(ok, msg):
    if not ok: raise ValueError(msg)


def area(cell):
    if cell.startswith(AW): return 'AXI AW source queue'
    if cell.startswith('chiptop0/system/chipyard_prcictrl_domain/clock_gater/'): return 'PRCI clock gater'
    if cell.startswith(('dutWrangler/','chiptop0/system/chipyard_prcictrl_domain/resetSynchronizer/')): return 'reset control'
    return 'other'


def operations(lines):
    """Associate an interval only if the named move and accepted net agree."""
    if len(lines)==2:
        m,b = MOVE.fullmatch(lines[0]),BETTER.fullmatch(lines[1]); require(m and b and m[1]==b[1], 'changed or mismatched move/net'); return 'move',m[1],m[2]
    # A failed optimization of one net can precede the successful replication
    # of another, without an intervening timing estimate. Preserve ambiguity.
    if len(lines)==3:
        fail=re.fullmatch(r'INFO: \[Physopt 32-702\] Processed net (\S+)\. Optimizations did not improve timing on the net\.',lines[0]); rep=re.fullmatch(r'INFO: \[Physopt 32-81\] Processed net (\S+)\. Replicated (\d+) times\.',lines[1]); b=BETTER.fullmatch(lines[2]); require(fail and rep and b and int(rep[2])>0 and rep[1]==b[1], 'incomplete multi-action interval'); return 'mixed',None,None
    raise ValueError('unrecognized timing interval')


def phase(body):
    prev=None; first=None; held=[]; stats=defaultdict(Counter); cells=set(); nets=set(); fields=Counter(); repeated=0
    for line in body.splitlines():
        if not line or line.startswith('Netlist sorting complete. Time (s):'): continue
        m=EST.fullmatch(line)
        if not m:
            require(prev is not None, 'missing initial estimate'); held.append(line); continue
        v=tuple(map(D,m.groups()))
        if prev is None: first=v
        elif held:
            kind,net,cell=operations(held); group=area(cell) if cell else 'mixed actions'; c=stats[group]
            delta=v[0]-prev[0]; c['intervals']+=1; c['wns_changes']+=int(delta!=0); c['delta']+=delta
            if kind=='move':
                if cell.startswith(AW):
                    field=re.fullmatch(r'mem_([0-7])_(addr|len|id|size)_reg\[(\d+)\]',cell[len(AW):]); require(field and int(field[3])<{'addr':32,'len':8,'id':4,'size':3}[field[2]] and net.startswith(AW), 'unknown AW payload bit');fields[field[2]]+=1
                cells.add(cell); nets.add(net)
        else:
            require(v==prev,'timing changed without an action'); repeated+=1
        prev=v; held=[]
    require(first and stats and not held and repeated==1, 'unfinished critical path phase')
    return first,prev,stats,cells,nets,fields


def analyze(block):
    term,=re.findall(r'^INFO: \[Physopt 32-603\] Post Physical Optimization Timing Summary \| WNS=('+NUM+r') \| TNS=('+NUM+r') \|$',block,re.M)
    phases=re.findall(r'^Phase (\d+) Critical Path Optimization$',block,re.M);require(phases==['32','33'], 'unexpected critical path phases')
    seen=set(); nets=set(); hist=Counter(); total=defaultdict(Counter); prev=None
    for i in phases:
        name=f'Phase {i} Critical Path Optimization'; rows,=re.findall(r'^'+name+r'\n([\s\S]*?)\n'+name+r' \| Checksum: [a-f\d]+$',block,re.M)
        first,last,counts,cells,nn,fs=phase(rows)
        if prev is not None: require(prev==first, 'gap between phases')
        else: start=first
        prev=last;seen.update(cells);nets.update(nn);hist.update(fs)
        for k,v in counts.items(): total[k].update(v)
    require(tuple(map(D,term))==prev,'later stage changed the reported ending estimate')
    gain,=re.findall(r'^\|  Critical Path\s+\|\s*('+NUM+r')\s*\|',block,re.M)
    require(D(gain)==prev[0]-start[0]==sum(c['delta'] for c in total.values()),'table/interval WNS mismatch')
    slr,=re.findall(r'^\|  SLR Crossing\s+\|\s*('+NUM+r')\s*\|\s*('+NUM+r')\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|',block,re.M)
    srows=re.findall(r'^INFO: \[Physopt 32-767\] Processed net \S+\.\s+Re-placed instance (\S+)$',block,re.M)
    require(len(srows)==int(slr[4])==block.count('[Physopt 32-767]'), 'SLR event count mismatch')
    stats={k:dict(intervals=c['intervals'],wns_changes=c['wns_changes'],observed_delta_ns=str(c['delta'])) for k,c in sorted(total.items())}
    summary=dict(late_start_wns_ns=str(start[0]),ending_estimate_wns_ns=term[0],ending_estimate_tns_ns=term[1],critical_path_table_gain_ns=gain,intervals_by_action=stats,aw_moved_bit_occurrences=dict(sorted(hist.items())),aw_unique_cells=sum(c.startswith(AW) for c in seen),slr=dict(optimization_event_count=len(srows),unique_named_cells=len(set(srows)),fp_pipeline_name_occurrences=sum(c.startswith(FP) for c in srows),wns_gain_ns=slr[0],tns_gain_ns=slr[1]))
    return summary,seen,nets,set(srows)


def verify_source(kit):
    # Prove the named enqueue bank is on the harness PLL side, not the UI clock.
    # This is static RTL wiring; it does not identify the path/edge Vivado timed.
    specs={'VCU118FPGATestHarness': [('ResetWrangler','dutWrangler',{'auto_in_0_clock':'_harnessSysPLL_clk_out1','auto_out_0_clock':'_dutWrangler_auto_out_0_clock'}),('harnessSysPLL','harnessSysPLL',{'clk_out1':'_harnessSysPLL_clk_out1'}),('XilinxVCU118MIG','mig',{'clock':'_dutWrangler_auto_out_0_clock'})], 'XilinxVCU118MIG':[('AXI4AsyncCrossingSource','axi4asource',{'clock':'clock'})], 'AXI4AsyncCrossingSource':[('AsyncQueueSource_AXI4BundleAW','nodeOut_aw_source',{'clock':'clock'})]}
    ids={}
    def src(name):
        b=(kit/'rtl'/(name+'.sv')).read_bytes(); ids[name+'.sv']=sha256(b).hexdigest(); return re.sub(r'//[^\n]*','',b.decode())
    for parent,items in specs.items():
        s=src(parent)
        for typ,name,ports in items:
            body,=re.findall(r'^\s*'+typ+r'\s+'+name+r'\s*\(([\s\S]*?)\);',s,re.M)
            for port,arg in ports.items(): require(re.findall(r'\.'+port+r'\s*\(\s*(\w+)\s*\)',body)==[arg], 'different source clock binding')
    require(len(re.findall(r'\bassign auto_out_0_clock = auto_in_0_clock;',src('ResetWrangler')))==1, 'clock wrangler no longer direct')
    s=src('AsyncQueueSource_AXI4BundleAW'); bank,=re.findall(r'always @\(posedge clock\) begin\s+(if \(_widx_T_1[\s\S]*?)\n  end\b',s)
    for i in range(8):
        cond=r"index == 3'h"+str(i) if i<7 else r'\(&index\)'
        chunk,=re.findall(r'if \(_widx_T_1 & '+cond+r'\) begin([\s\S]*?)\bend\b',bank)
        for f in ('addr','id','len','size'): require(len(re.findall(r'\bmem_'+str(i)+'_'+f+r' <= io_enq_bits_'+f+';',chunk))==1,'missing enqueue payload write')
    return ids


def exact_hits(hops,cells,nets):
    # Strip only the final pin. Do not strip bus indices, hierarchy or replica suffixes.
    hit_cells={p.rsplit('/',1)[0] for h in hops for p in (h['driver'],h['sink'])} & cells
    hit_nets={h['net'] for h in hops} & nets
    return dict(exact_moved_cells=len(hit_cells),exact_processed_nets=len(hit_nets),aw_cells=sum(c.startswith(AW) for c in hit_cells),aw_nets=sum(n.startswith(AW) for n in hit_nets),aw_moved_input_pins=dict(sorted(Counter(h['sink'].rsplit('/',1)[1] for h in hops if h['sink'].rsplit('/',1)[0] in hit_cells and h['sink'].startswith(AW)).items())))


def endpoints(raw,cells):
    table=csv.DictReader(io.StringIO(raw.decode()),delimiter='\t')
    require(table.fieldnames==['destination_clock','kind','slack_ns','logic_levels','from','to'], 'wrong endpoint table')
    groups=defaultdict(list)
    for row in table:
        require(all(row.get(k) for k in table.fieldnames) and None not in row and row['kind'] in ('max','min'), 'invalid endpoint')
        groups[row['destination_clock'],row['kind']].append(row)
    require(groups,'empty endpoint table'); inventory=[]
    for (clock,kind),rows in sorted(groups.items()):
        slacks=[D(r['slack_ns']) for r in rows]
        require(len(rows)<=40 and len(set(r['to'] for r in rows))==len(rows) and all(x.is_finite() for x in slacks) and slacks==sorted(slacks), 'unsorted or repeated endpoints')
        matches=[]
        for i,r in enumerate(rows,1):
            pins={k:r[k].rsplit('/',1)[-1] for k in ('from','to') if r[k].rsplit('/',1)[0] in cells and r[k].startswith(AW)}
            if pins: matches.append(dict(rank=i,slack_ns=r['slack_ns'],pins=pins))
        inventory.append(dict(destination_clock=clock,kind=kind,sampled=len(rows),worst_sample_ns=rows[0]['slack_ns'],aw_endpoint_matches=matches))
    return inventory


def review(log,kit,run,with_route=False):
    place=PLACE['review'](log,kit,run/'obj',1); ref=json.loads((HERE.parent/'docs/perf175-placement.json').read_bytes())['four_wide']
    require(place==ref,'changed placement evidence')
    data=log.read_bytes().replace(b'\r\n',b'\n'); _,place=data.split(b'\nVCU118_STAGE=place\n'); place=place.split(b'\nVCU118_STAGE=route\n')[0]
    _,p=place.split(b'\nplace_design completed successfully\n'); prefix,block=p.split(b'\nCommand: phys_opt_design -directive Explore\n'); body,tail=block.split(b'\nphys_opt_design completed successfully\n')
    require(b'\nCommand: power_opt_design\n' in tail and b'VCU118_STAGE=' not in prefix,'wrong implementation phase')
    require(sha256(body).hexdigest()==BODY_SHA,'changed completed physical-optimization segment')
    summary,cells,nets,slr=analyze(body.decode()); result=dict(scope='Four-wide original placement only; association between successive global estimates is not path attribution, routed slack, CPU frequency or board evidence.',board_input_seal=ref['board_input_seal'],post_opt_sha256=ref['post_opt_dcp_sha256'],physopt_body_lf_sha256=sha256(body).hexdigest(),rtl_sha256=verify_source(kit),**summary)
    if with_route:
        a=HOPS['ROUTED']['mega'](run,kit,log); samples={}; folder=run/'obj/routed-endpoints'
        for typ,g in a['paths'].items():
            f=folder/(HOPS['ROUTED']['CLOCK']+'-'+typ+'.rpt'); raw=f.read_bytes(); require(sha256(raw).hexdigest()==a['report_hashes'][f.name],'changed path file')
            sections=re.split(r'(?m)(?=^Slack \((?:MET|VIOLATED)\)\s*:)',raw.decode().replace('\r\n','\n'))[1:];require(len(sections)==len(g['details'])==8,'incomplete sample')
            samples[typ]=[]
            for i,(section,d) in enumerate(zip(sections,g['details']),1):
                h=HOPS['decompose'](section,d); touched={p.rsplit('/',1)[0] for row in h for p in (row['driver'],row['sink'])} & slr
                samples[typ].append(dict(rank=i,slack_ns=d['slack_ns'],exact_slr_named_cells=len(touched),fp_among_slr_cells=sum(c.startswith(FP) for c in touched),**exact_hits(h,cells,nets)))
        t=folder/'endpoints.tsv'; b=t.read_bytes();require(sha256(b).hexdigest()==a['report_hashes'][t.name],'changed endpoint table')
        result['scope']='Placed events vs same-build routed sampled data only; agreement on a name is not proof of a causal delay, or full timing/CDC/board signoff.'
        result['routed_cpu_sample']=dict(all_clock_endpoint_inventory=endpoints(b,cells),dcp_sha256=a['post_route_dcp_sha256'],report_sha256=a['report_hashes'],directions=samples)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('log','kit','run'):p.add_argument(k,type=Path)
    p.add_argument('--routed-cpu',action='store_true');a=p.parse_args();print(json.dumps(review(a.log,a.kit,a.run,a.routed_cpu),indent=2))
