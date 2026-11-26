#!/usr/bin/env python3
"""Inventory Vivado 2024.2 missing I/O-delay details; never waive a timed interface."""
import re

# This is a routing inventory, not external-device timing signoff. The shell
# uses SD socket names in SPI mode: its `cs` pin actually carries MOSI.
KNOWN = {
    'input': {
        'jtag_jtag_TDI': ('AP15','FMC soft-core TAP TDI, synchronous to JTCK'),
        'jtag_jtag_TMS': ('AN15','FMC soft-core TAP TMS, synchronous to JTCK'),
        'reset': ('L19','asynchronous board reset/POR/PLL/wrangler'),
        'sdio_spi_dat_0': ('AW15','J52.5 SPI MISO through U41'),
        'uart_rxd': ('AW25','J4 FPGA-side UART RX, asynchronous'),
    },
    'output': {
        'ddr_c0_ddr4_reset_n': ('N20','MIG DDR4 RESET_n; verify IP reset sequence and calibration'),
        'jtag_jtag_TDO': ('AM12','FMC soft-core TAP TDO return'),
        'sdio_spi_clk': ('AV15','J52.7 SPI SCLK through U41'),
        'sdio_spi_cs': ('AY15','J52.3 SPI MOSI through U41 (not chip select)'),
        'sdio_spi_dat_3': ('AY14','J52.1 SPI CS_n through U41'),
        'uart_txd': ('BB21','J4 FPGA-side UART TX, asynchronous serial'),
    }
}

def check_io(text, counts):
    out={}; known=True
    for d in ('input','output'):
        key='no_'+d+'_delay'; n=counts[key]
        match=re.findall(r'^\s*\d+\. checking '+key+r' \(\d+\)\r?\n-+\s*\n(.*?)(?=^\s*\d+\. checking |\Z)',text,re.M|re.S)
        if len(match)!=1: raise ValueError('missing or duplicate I/O detail section '+key)
        # A later sentence lists e.g. ports with false-path exceptions; do
        # not silently classify those as covered by this primary inventory.
        parts=re.split(r'^\s*There (?:are|is) ',match[0],flags=re.M)
        if len(parts)<2 or parts[0].strip():raise ValueError('unrecognized section '+key)
        summary,*pins=parts[1].strip().splitlines(); pins=[p.strip() for p in pins if p.strip()]
        h=re.fullmatch(r'(\d+) (?:'+d+r' )?ports? with no '+d+r' delay specified\.(?:\s*\(HIGH\))?',summary.strip())
        if not h or int(h[1])!=n or len(pins)!=n or len(set(pins))!=n or not all(re.fullmatch(r'[\w\[\]./-]+',p) for p in pins):raise ValueError('I/O count, names or summary not reconciled: '+key)
        other=[]
        for more in parts[2:]:
            desc=more.strip().splitlines(); mh=re.match(r'(\d+) ',desc[0]);
            if not mh:raise ValueError('unclassified supplementary I/O check: '+key)
            if int(mh[1]): other.append(desc[0])
        # A new exempt/clocked pin deserves an explicit interface review too.
        unknown=sorted(set(pins)-KNOWN[d].keys());known=known and not unknown and not other
        out[d]={'unconstrained_ports':{p:list(KNOWN[d].get(p,('unknown','not reviewed'))) for p in pins},'unknown_ports':unknown,'additional_nonzero_checks':other}
    return out,known
