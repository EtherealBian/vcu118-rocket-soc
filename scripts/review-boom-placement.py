#!/usr/bin/env python3
"""Compare placement evidence of the sealed 175 MHz designs, not routed timing."""
import argparse
import json
from hashlib import sha256
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
synth = runpy.run_path(str(HERE/'review-boom-synth-footprint.py'))
OPT_SHA = ('592e127cae12ede785e506b3d96eab099ea4918f4cde3aeb88241832a7c67a20',
           '98e6d4f6c545a4f0f07c0618dad28e5de23dc9330ff98bc2cc81d2038a54db5f')


def single(pattern, text):
    hits = re.findall(pattern, text, re.M)
    if len(hits) != 1:
        raise ValueError('missing or ambiguous placement evidence: '+pattern)
    return hits[0]


def regions(text):
    tables = re.split(r'^SLR(\d+):\s*$', text, flags=re.M)
    if tables[1::2] != ['0','1','2']:
        raise ValueError('expected three ordered SLR tables')
    result = {}
    for scope, body in zip(('device','SLR0','SLR1','SLR2'), tables[::2]):
        single(r'^\| *\| Global Congestion \| Long Congestion +\| Short Congestion +\| *$', body)
        rows = re.findall(r'^\| *(North|South|East|West)\| *(\d+x\d+)\| *(\d+x\d+)\| *(\d+x\d+)\| *$', body, re.M)
        if [row[0] for row in rows] != ['North','South','East','West']:
            raise ValueError('incomplete or repeated direction')
        result[scope] = {row[0]:dict(zip(('global','long','short'),row[1:])) for row in rows}
    return result


def placed(text, opt):
    _, stage = text.split('\nVCU118_STAGE=opt\n')
    before, after = stage.split('\nVCU118_STAGE=place\n')
    path = single(r"^INFO: \[Common 17-1381\] The checkpoint '([^']+/post_opt.dcp)' has been generated\.$", before)
    if synth['portable'](path) != synth['portable'](opt.resolve()):
        raise ValueError('foreign checkpoint')
    _, stage = after.split('\nCommand: place_design -directive Explore\n')
    block, _ = stage.split('\nplace_design completed successfully\n', 1)
    early, tns = single(r'^INFO: \[Physopt 32-619\] Estimated Timing Summary \| WNS=(-?\d+\.\d+) \| TNS=(-?\d+\.\d+) \|$', block)
    def estimate(rule, label):
        return single('^INFO: \\['+rule+'\\] '+label+r' Timing Summary WNS=(-?\d+\.\d+)\. For the most accurate timing information please run report_timing\.$', block)
    post = estimate('Place 30-746','Post Placement')
    repl = estimate('Place 46-19','Post Replication')
    table, checksum = single(r'(?s:^INFO: \[Place 30-612\] Post-Placement Estimated Congestion *\n(.+?)\nPhase 4\.3\.1 Print Estimated Congestion \| Checksum: ([0-9a-f]+)$)',block)
    info, warnings = single(r'^(\d+) Infos, (\d+) Warnings, 0 Critical Warnings and 0 Errors encountered\.$',block)
    alerts = re.findall(r'^WARNING: \[Place 46-14\] .+$',block,re.M)
    if len(alerts)>1:raise ValueError('ambiguous congestion warning')
    return dict(before_bufg_wns_ns=early,before_bufg_tns_ns=tns,post_placement_wns_ns=post,post_replication_wns_ns=repl,
                regions=regions(table),congestion_table_sha256=sha256(table.encode()).hexdigest(),placer_congestion_checksum=checksum,
                place_46_14=bool(alerts),placer_messages=dict(info=int(info),warnings=int(warnings),critical_warnings=0,errors=0))


def review(log, kit, obj, i):
    known=json.loads((HERE.parent/'docs/perf175-synth-footprint.json').read_bytes())[['three_wide_stock','four_wide_split'][i]]
    if synth['review'](log,kit,obj/'post_synth.dcp',synth['SEALS'][i])!=known:
        raise ValueError('foreign board synthesis')
    opt=obj/'post_opt.dcp'
    if synth['digest'](opt)!=OPT_SHA[i]: raise ValueError('foreign optimized design')
    return dict(board_input_seal=known['board_input_seal'],post_opt_dcp_sha256=OPT_SHA[i],**placed(log.read_text(errors='replace'),opt))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('three_log','three_kit','three_obj','four_log','four_kit','four_obj'):p.add_argument(k,type=Path)
    a=p.parse_args(); records=[review(*(getattr(a,prefix+'_'+k) for k in ('log','kit','obj')),i) for i,prefix in enumerate(('three','four'))]
    print(json.dumps(dict(scope='Whole-design placer estimates only. Region size is not utilization or a count of failing paths. Does not identify a CPU path, measured Fmax or score. The two organizations and debug revisions differ.',three_wide=records[0],four_wide=records[1]),indent=2))
