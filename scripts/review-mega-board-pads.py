#!/usr/bin/env python3
"""Check native pad probe results before exporting the path-free comparison."""
import argparse
import csv
import json
import re
import runpy
from zipfile import ZipFile
from pathlib import Path

common = runpy.run_path(str(Path(__file__).with_name('test-mega-board-pads.py')))
need, h = common['need'], common['h']
inputs, outputs = common['INPUTS'], common['OUTPUTS']
pads = common['PADS']


def read_ports(folder, case):
    with (folder/'ports.tsv').open(newline='') as f:
        rows = list(csv.DictReader(f,delimiter='\t'))
    need(len(rows)==10 and {r['pad'] for r in rows}==set(pads),'incomplete boundary inventory')
    for r in rows:
        p=r['pad']; inp=p in inputs
        direction='INOUT' if case=='stock' else ('IN' if inp else 'OUT')
        boundary=('INBUF','PAD','-') if inp else (('OBUFT','O','T=NOT_VCC') if case=='stock' else ('OBUF','O','-'))
        need((r['direction'],r['package_pin'],r['standard'])==(direction,pads[p][0],'LVCMOS18'),'pad assignment mismatch: '+p)
        need((r['primitive'],r['primitive_pin'],r['drive_enable'])==boundary,'pad buffer mismatch: '+p)
    return rows


def read_sim(folder, prep):
    data=json.loads((folder/'sim.json').read_bytes()); log=(folder/'xsim.log.txt').read_text()
    need(not re.search(r'(?mi)^\s*(?:ERROR|FATAL):',log) and '$finish called at time' in log,'incomplete simulation')
    need(re.findall(r'^PAD_COMPARE samples=(\d+) negative=(\d+)\s*$',log,re.M)==[('1044','516')], 'different simulation outcome')
    need(data==dict(samples=1044, all_binary_combinations=1024, extra_x_or_z_samples=20,
                    wrong_spi_select_disagreements=516,testbench_sha256=h((folder/'tb.sv').read_bytes()),
                    fixture_inputs_sha256=h((prep/'inputs.json').read_bytes())), 'simulation manifest mismatch')
    return data


def native(folder, case, rule, filename, command):
    prop=(folder/(rule+'-properties.txt')).read_text()
    for key, value in [('IS_ENABLED','1'),('IS_USER_DEFINED','0'),('MAX_MESSAGES','-1'),('SEVERITY','Warning'),('NAME',rule)]:
        need(re.search(r'^'+key+r'\s+\S+\s+(true|false)\s+'+value+r'\s*$',prop,re.M),'native rule property: '+key)
    rpt=(folder/filename).read_text()
    for marker in ['Vivado v.2024.2','io_fixture','xcvu9p-flga2104-2L-e',command+' -checks '+rule+' -file '+filename]:
        need(marker in rpt,'wrong native report: '+marker)
    expected=set() if case=='typed' else (set(pads) if rule=='RPBF-3' else set(outputs))
    pat=(r'Device port (\w+) expects both input and output buffering' if rule=='RPBF-3' else r'Hierarchical port\(pin\) (\w+) direction INOUT')
    hits=re.findall(r'^'+rule+r'#\d+ Warning\n[^\n]*\n'+pat,rpt,re.M)
    need(len(hits)==len(expected) and set(hits)==expected,'different native rule details: '+rule)
    need(re.search(r'(?m)^\s*Checks:\s*'+rule+r'\s*$',rpt) and re.findall(r'(?m)^\s*Checks found:\s*(\d+)\s*$',rpt)==[str(len(expected))], 'missing native coverage/count: '+rule)
    return sorted(hits)


def review(prep, sim, stock, typed):
    common['check'](prep); meta=json.loads((prep/'inputs.json').read_bytes()); cases={}
    for case,folder in [('stock',stock),('typed',typed)]:
        rows=read_ports(folder,case)
        with ZipFile(folder/'synthesized.dcp') as z:
            stub=z.read('io_fixture_stub.v').decode()
        for r in rows:
            decl={'INOUT':'inout','IN':'input','OUT':'output'}[r['direction']]
            need(re.findall(r'^\s*(inout|input|output)\s+'+r['pad']+r';',stub,re.M)==[decl],'checkpoint does not match ports: '+r['pad'])
        rp=native(folder,case,'RPBF-3','drc.rpt','report_drc')
        hp=native(folder,case,'HPDR-1','methodology.rpt','report_methodology')
        files=('ports.tsv','drc.rpt','methodology.rpt','synthesized.dcp','RPBF-3-properties.txt','HPDR-1-properties.txt')
        cases[case]=dict(ports=rows,rpbf_ports=rp,hpdr_ports=hp,sha256={n:h((folder/n).read_bytes()) for n in files})
    return dict(scope='Isolated synthesized shell-pin fixtures only. Neither placed nor routed; not integrated or tested on hardware.',
                tool='Vivado 2024.2',part='xcvu9p-flga2104-2L-e',fixture_input_sha256=common['INPUT_SEAL'],
                source_seals=meta['source_seals'],archived_report_sha256=meta['archived_report_sha256'],
                simulation=read_sim(sim,prep),synthesized=cases)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('prepared','sim','stock','typed'): p.add_argument(name,type=Path)
    p.add_argument('--output',type=Path); a=p.parse_args()
    text=json.dumps(review(a.prepared,a.sim,a.stock,a.typed),indent=2)+'\n'
    if a.output:
        with a.output.open('xb') as f:f.write(text.encode())
    else: print(text,end='')
