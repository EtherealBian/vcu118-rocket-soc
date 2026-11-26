#!/usr/bin/env python3
"""Fail closed on missing coverage; still requires human pin/CDC/DRC review before configuration."""
import argparse, hashlib, importlib.util, json, re
from pathlib import Path
spec=importlib.util.spec_from_file_location('vcu_report',Path(__file__).with_name('review-fpga.py'))
r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

def check_fixture(read):
    def need(report, pattern):
        if not re.search(pattern,read(report),re.M): raise ValueError('unexpected '+report+' report: '+pattern)
    for report in ('drc','methodology'):
        if re.findall(r'^\s*Checks found:\s*(\d+)\s*$',read(report),re.M)!=['0']:
            raise ValueError('expected exactly zero '+report+' findings')
    need('clocks',r'^sys_clock\s+4\.000\s+.*\{sys_clock_p\}\s*$'); need('clocks',r'^clk_raw\s+10\.000\s+.*\{mmcm/CLKOUT0\}\s*$')
    pins={'AW25':('uart_rxd','INPUT','LVCMOS18'),'BB21':('uart_txd','OUTPUT','LVCMOS18'),
          'E12':('sys_clock_p','INPUT','DIFF_SSTL12'),'D12':('sys_clock_n','INPUT','DIFF_SSTL12')}
    for pin,(signal,direction,standard) in pins.items():
        rows=[[cell.strip() for cell in x.split('|')] for x in read('io').splitlines() if x.startswith('|')]
        matches=[r for r in rows if len(r)>7 and r[1]==pin]
        if len(matches)!=1 or (matches[0][2],matches[0][6],matches[0][7])!=(signal,direction,standard) or 'FIXED' not in matches[0]:
            raise ValueError('unexpected package pin '+pin)
    if re.findall(r'^CDC-([0-9]+)\s+(\S+)\s+(\d+)\s+',read('cdc'),re.M)!=[('3','Info','1')]: raise ValueError('unexpected CDC summary')
    need('cdc',r'^\s*1\s+CDC-3\s+Info\s+.*\s2\s+False Path\s+uart_rxd\s+rx_meta_reg/D\s*$')
    ct=r.counters(read('check')); keys='no_clock constant_clock pulse_width_clock unconstrained_internal_endpoints no_input_delay no_output_delay multiple_clock generated_clocks loops partial_input_delay partial_output_delay latch_loops'.split()
    if ct!={k:int(k in ('no_input_delay','no_output_delay')) for k in keys}: raise ValueError('unexpected timing coverage: '+str(ct))
    for which,port in [('input','uart_rxd'),('output','uart_txd')]:
        need('check',r'There (?:is|are) 0 (?:input )?ports with no '+which+r' delay specified\.')
        need('check',r'There is 1 (?:input )?port with no '+which+r' delay but user has a false path constraint[^\n]*\n\s*'+port+r'\s*$')
    return ct

def review(run):
    sha=lambda data:hashlib.sha256(data).hexdigest()
    e=json.loads((run/'build-evidence.json').read_text(encoding='utf-8-sig'))
    src={'rtl/boardprobe/probe_protocol.sv','rtl/boardprobe/vcu118_probe.sv','rtl/boardprobe/probe.xdc','scripts/build-board-probe.tcl'}
    if set(e['sources'])!=src or any(sha((run/'source'/k).read_bytes())!=v for k,v in e['sources'].items()):
        raise ValueError('source snapshot/hash mismatch')
    log=(run/'vivado.log').read_bytes(); text=log.decode(errors='replace')
    if sha(log)!=e['log_sha256'] or re.search(r'^(CRITICAL WARNING|ERROR):',text,re.M) or not re.search(r'^VCU118_PROBE_BIT_WRITTEN\s*$',text,re.M):
        raise ValueError('build log mismatch, critical warning, error or missing completion')
    run=run/'impl'
    required='route timing check cdc exceptions io clocks resources drc methodology'.split()
    files={name:(run/(name+'.rpt')).read_bytes() for name in required}
    if not all(files.values()): raise ValueError('empty report')
    read=lambda k:files[k].decode(errors='replace')
    route=r.route(read('route')); timing=r.timing(read('timing')); cov=check_fixture(read)
    # Asynchronous IO (one RX, one TX) is reviewed separately. Internal endpoints may not be unconstrained.
    if not r.gates(route,timing) or cov['no_clock'] or cov['unconstrained_internal_endpoints']:
        raise ValueError(f'probe route/timing rejected: {route}, {timing}, {cov}')
    bit=(run/'probe.bit').read_bytes()
    if sha(bit)!=e['bit_sha256'] or len(bit)<1024 or b'vcu118_probe' not in bit[:512]: raise ValueError('wrong/empty bitstream header')
    return dict(design='vcu118_probe',scope='board fixture only, no CPU or DDR',route=route,timing=timing,coverage=cov,
                bit_sha256=sha(bit),reports={k:sha(v) for k,v in files.items()})
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('run',type=Path); print(json.dumps(review(ap.parse_args().run),indent=2))
