#!/usr/bin/env python3
"""Compare static clock, pin, DDR-IP and exception inputs, not routed constraints."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy

HERE=Path(__file__).resolve().parent
SEALS=('e28f9b3cbadbff993bf9d0861776490e841e1b613dfc5bc81ed194b4c2db571e','b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959')

def digest(data): return sha256(data).hexdigest()

def pll_delta(low,high):
    def normalize(data,mhz):
        lo,hi=('99.0','101.0') if mhz==100 else ('173.25','176.75')
        text=data.decode('ascii')
        for a,b in [(f'CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {{{mhz}.0}}','CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {REQUEST}'),(f'if {{$freq < {lo} || $freq > {hi}}}', 'if {$freq < LOWER || $freq > UPPER}'),(f'outside tolerated range {lo}-{hi}','outside tolerated range LOWER-UPPER')]:
            if text.count(a)!=1:raise ValueError('unrecognized PLL request or guard')
            text=text.replace(a,b)
        return text
    if normalize(low,100)!=normalize(high,175):raise ValueError('PLL change outside request and guard')

def exceptions(sdc,xdc):
    sdc=sdc.decode('ascii');xdc=xdc.decode('ascii'); joined=sdc.replace('\\\n',' ')
    commands=[line.split()[0] for line in joined.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if commands!=['create_clock','set_input_jitter','create_clock','set_input_jitter','set_clock_groups','set_false_path']:raise ValueError('unexpected shell SDC commands')
    clocks=re.findall(r'^create_clock -name (\S+) -period (\S+) \[get_ports \{([^}]+)\}\]$',joined,re.M)
    if clocks!=[('sys_clock','4.0','sys_clock_p'),('JTCK','100.0','jtag_jtag_TCK')]:raise ValueError('unexpected shell clock')
    groups=[x for x in joined.splitlines() if x.startswith('set_clock_groups ')]; expected='set_clock_groups -asynchronous -group [list [get_clocks -of_objects [get_pins { mig/island/blackbox/c0_ddr4_ui_clk }]]] -group [list [get_clocks -of_objects [get_pins { harnessSysPLL/clk_out1 }]]] -group [list [get_clocks { JTCK }]]'
    if [' '.join(x.split()) for x in groups]!=[expected]:raise ValueError('unexpected clock groups')
    if re.findall(r'^set_false_path.*$',sdc,re.M)!=['set_false_path -through [get_pins {fpga_power_on/power_on_reset}]']:raise ValueError('unexpected shell false path')
    if re.findall(r'^.*CLOCK_DEDICATED_ROUTE.*$',xdc,re.M)!=['set_property CLOCK_DEDICATED_ROUTE {FALSE} [get_nets [get_ports {jtag_jtag_TCK}]]']:raise ValueError('unexpected dedicated route override')
    return dict(primary_clocks_ns={'sys_clock':4,'JTCK':100},asynchronous_groups=['MIG UI','system PLL output','external JTCK'],shell_false_path_through='fpga_power_on/power_on_reset',dedicated_route_override_port='jtag_jtag_TCK')

def review(low,high):
    suffixes=('shell.sdc','shell.xdc','shell.vivado.tcl','vcu118mig.vivado.tcl','harnessSysPLL.vivado.tcl'); rows=[]
    for kit,want in zip((low.resolve(),high.resolve()),SEALS):
        if digest((kit/'CANDIDATE.sha256').read_bytes())!=want:raise ValueError('different sealed design')
        runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals'](kit)
        values={}
        for suffix in suffixes:
            only,=(kit/'board').glob('*.'+suffix);values[suffix]=only.read_bytes()
        values['master.xdc']=(kit/'shell/xilinx/vcu118/constraints/vcu118-master.xdc').read_bytes()
        if list(kit.rglob('*.extra.shell.xdc')):raise ValueError('unreviewed optional constraints')
        rows.append(values)
    a,b=rows; pll='harnessSysPLL.vivado.tcl'; pll_delta(a[pll],b[pll]); common={k:digest(v) for k,v in a.items() if k!=pll}
    if any(a[k]!=b[k] for k in common):raise ValueError('shell, MIG or master constraint inputs differ')
    return dict(scope='Static comparison of two sealed implementation kits only. Generated IP constraints, synthesis elaboration, effective clock coverage, CDC, routed timing/DRC and I/O require review on the four-wide run. No permission to program.',rocket_reference_kit=SEALS[0],four_wide_kit=SEALS[1],identical_file_sha256=common,pll_file_sha256={'rocket100':digest(a[pll]),'mega175':digest(b[pll])},pll_change='Only CLKOUT1 request, allowed range and diagnostic text (100 to 175 MHz).',**exceptions(b['shell.sdc'],b['shell.xdc']))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('reference',type=Path);p.add_argument('candidate',type=Path);a=p.parse_args();print(json.dumps(review(a.reference,a.candidate),indent=2))
