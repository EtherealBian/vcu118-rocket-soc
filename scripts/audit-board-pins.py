#!/usr/bin/env python3
"""Compare all named IOs of a routed VCU118 SoC with board data, then check the generated MIG configuration. No hardware access."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


# UG1224 v1.4 tables 3-30 and 3-31: package and connector coordinates.
# The shell uses the FMC LA pins single-ended. LVCMOS18 here is the design's
# intended nominal operating point, NOT a rail measurement or cable qualification.
CONNECTORS = {
    'jtag_srst_n': ('AK12', 'J2.H34'), 'jtag_jtag_TCK': ('AL12', 'J2.H35'),
    'jtag_jtag_TDO': ('AM12', 'J2.G34'), 'jtag_jtag_TMS': ('AN15', 'J2.G30'),
    'jtag_jtag_TDI': ('AP15', 'J2.G31'), 'sdio_spi_dat_3': ('AY14', 'J52.1'),
    'sdio_spi_cs': ('AY15', 'J52.3'), 'sdio_spi_dat_0': ('AW15', 'J52.5'),
    'sdio_spi_clk': ('AV15', 'J52.7'), 'sdio_spi_dat_1': ('AV16', 'J52.2'),
    'sdio_spi_dat_2': ('AU16', 'J52.4'),
}
XML_HASH = {'board.xml': 'c8ac84d9a89d1527b8465e95617bb695e5dba0e3313d7608db78a8936cf3bf6e',
            'part0_pins.xml': '3ae9e6fc8cb2bb59de49c6b30238a5e1fd74a9318399de658d85ba6d349402fa'}


def digest(blob): return hashlib.sha256(blob).hexdigest()


def expected(board_dir):
    roots = {}
    for name, sha in XML_HASH.items():
        raw = (board_dir / name).read_bytes()
        if digest(raw) != sha: raise ValueError('unreviewed VCU118 board reference: '+name)
        roots[name] = ET.fromstring(raw)
    pins = {x.attrib['name']: x.attrib for x in roots['part0_pins.xml'].findall('./pins/pin')}
    board = roots['board.xml']; want = {}
    def add(port, ref, use, bank, std=None):
        p = pins[ref]
        want[port] = (p['loc'], use, p['iostandard'] if std is None else std, str(bank), 'FIXED')
    # UG1224 Table 3-2: C1 package wiring; the vendor IP's C0 is an instance label.
    lane_banks = [71, 73, 73, 73, 73, 72, 72, 72]
    for bus, width in {'adr':17,'ba':2,'dq':64,'dqs_c':8,'dqs_t':8,'dm_dbi_n':8}.items():
        data = bus not in ('adr', 'ba')
        for i in range(width):
            add(f'ddr_c0_ddr4_{bus}[{i}]', f'c1_ddr4_{bus}{i}', 'BIDIR' if data else 'OUTPUT', lane_banks[i//8 if bus=='dq' else i] if data else 71)
    for pad in ('act_n','bg','ck_t','ck_c','cke','cs_n','odt','reset_n'):
        add('ddr_c0_ddr4_'+pad,'c1_ddr4_'+pad,'OUTPUT',72 if pad=='reset_n' else 71)
    for p in ('p','n'): add('sys_clock_'+p, 'default_250mhz_clk1_'+p, 'INPUT', 71)
    add('reset', 'CPU_RESET', 'INPUT', 73)
    for sig, logical, direction in [('TX','TxD','out'), ('RX','RxD','in')]:
        ref = 'USB_UART_'+sig
        p = board.findall(f".//interface[@name='rs232_uart']/port_maps/port_map[@logical_port='{logical}'][@dir='{direction}']/pin_maps/pin_map[@component_pin='{ref}']")
        v = board.findall(f".//component[@name='rs232_uart']/pins/pin[@name='rs232_uart_USB_{sig}']")
        if len(p)!=1 or len(v)!=1: raise ValueError('ambiguous UART board mapping')
        add('uart_'+sig.lower()+'d', ref, 'BIDIR', 64, v[0].attrib['iostandard'])
    # CP2105 RTS drives FPGA CTS; FPGA RTS drives CP2105 CTS (UG1224 table 3-26).
    add('uart_ctsn','USB_UART_RTS','BIDIR',64); add('uart_rtsn','USB_UART_CTS','BIDIR',64)
    for name,(loc,_) in CONNECTORS.items(): want[name] = (loc, 'BIDIR', 'LVCMOS18', '67', 'FIXED')
    return want


def audit_io(text, want):
    total = re.findall(r'\| Total User IO \|\s*\n[^\n]+\n\|\s*(\d+)\s*\|',text)
    hdr=None; seen={}; locs=set(); keys=['Pin Number','Use','IO Standard','IO Bank','Constraint']
    for row in text.splitlines():
        if not row.startswith('|'): continue
        c=[s.strip() for s in row.strip().strip('|').split('|')]
        if 'Signal Name' in c:
            if hdr or not set(keys)<=set(c): raise ValueError('unexpected report_io header')
            hdr=c; continue
        if not hdr or len(c)!=len(hdr): continue
        r=dict(zip(hdr,c)); name=r['Signal Name']
        if not name: continue
        got=tuple(r[k] for k in keys)
        if name in seen or got[0] in locs: raise ValueError('duplicate assigned port/pin: '+name)
        if want.get(name)!=got: raise ValueError(f'unexpected {name}: {got} (expected {want.get(name)})')
        seen[name]=got; locs.add(got[0])
    if total!=[str(len(want))] or seen.keys()!=want.keys(): raise ValueError('incomplete named I/O coverage: '+str(sorted(want.keys()-seen.keys())))
    return dict(total=len(seen), ddr_c1=sum(n.startswith('ddr_c0_ddr4_') for n in seen),
                io_banks=dict(sorted(Counter(v[3] for v in seen.values()).items())), board_reference_sha256=XML_HASH)


def audit_ip(raw):
    inst=json.loads(raw)['ip_inst']; params=inst['parameters']; ref='xilinx.com:ip:ddr4:2.2'
    if inst['component_reference']!=ref or inst['xci_name']!='vcu118mig': raise ValueError('wrong MIG instance')
    spec={'C0.DDR4_MemoryPart':'MT40A256M16GE-083E','C0.DDR4_MemoryType':'Components','C0.DDR4_DataWidth':'64',
          'C0.DDR4_Ecc':'false','C0.DDR4_AxiAddressWidth':'31','C0.DDR4_AxiDataWidth':'64','C0.DDR4_AxiIDWidth':'4',
          'C0.DDR4_TimePeriod':'1250','C0.DDR4_PhyClockRatio':'4:1','C0.DDR4_CLKFBOUT_MULT':'8','C0.DDR4_DIVCLK_DIVIDE':'2','C0.DDR4_CLKOUT0_DIVIDE':'5'}
    for k,v in spec.items():
        if [p['value'] for p in params['component_parameters'][k]]!=[v]: raise ValueError('unexpected MIG setting: '+k)
    if [p['value'] for p in params['model_parameters']['CAL_INPUT_CLK_PERIOD']]!=['4000']: raise ValueError('generated calibration clock is not 4000 ps')
    return dict(component=ref,device=spec['C0.DDR4_MemoryPart'],axi_address_bits=31,axi_data_bits=64,ddr_data_bits=64,ddr_ck_ps=1250,cal_input_clock_ps=4000)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('run',type=Path);ap.add_argument('board_definition',type=Path);a=ap.parse_args()
    obj=a.run/'obj'; raw=(obj/'routed-io.rpt').read_bytes(); ip=(obj/'ip/vcu118mig/vcu118mig.xci').read_bytes()
    r=audit_io(raw.decode(),expected(a.board_definition));r.update(mig=audit_ip(ip),io_sha256=digest(raw),xci_sha256=digest(ip),
        scope='Pad assignments and generated IP configuration only; not active IOB directions, external timing, supply voltage, calibration or board execution.')
    print(json.dumps(r,indent=2))

if __name__=='__main__': main()
