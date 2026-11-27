"""Only reviewed physical builds can label a matrix with a CPU and clock.

This table is not permission to program an FPGA. The collection path separately
verifies programming readback, the live guest, and the benchmark payload.
"""
from decimal import Decimal
from hashlib import sha256
import re

ROCKET_BIT = 'd77b13dbf75b4773e33ba48f7b177f320572cb62ffe8a9cd930ab196edd6f520'
HARDWARE = {
    ROCKET_BIT: dict(name='Rocket split-halt', physical_harts=1, mhz=100,
                     reports={'routed-clocks.rpt':'2b135964b838898b80065e8243824b82ab66cf71df5d952a00d0b3a1eeeaa1b5',
                              'full-timing.rpt':'92f6928ce9a3e7b865f2df92fae10c23b68f034766d557b061f38326a2d378cb'}),
}


def lookup(bit):
    if bit not in HARDWARE:
        raise ValueError('no reviewed benchmark hardware for this bit')
    return HARDWARE[bit]


def verify(boot, report_dir, captured):
    bit=boot['bit_sha256']; hw=lookup(bit)
    if captured['bit_sha256'] != bit or not all(captured.get(k) is True for k in (
            'board_io_inventory_known','board_internal_coverage_met','route_and_constrained_timing_met')):
        raise ValueError('capture not bound to routed benchmark hardware')
    for name, wanted in hw['reports'].items():
        data=(report_dir/name).read_bytes()
        if captured['reports_sha256'].get(name)!=wanted or sha256(data).hexdigest()!=wanted:
            raise ValueError('benchmark hardware report mismatch: '+name)
        if name=='routed-clocks.rpt':
            periods=re.findall(rb'^clk_out1_harnessSysPLL[ \t]+([0-9]+\.[0-9]+)[ \t]+\{[^\r\n]+\}[ \t]+P,G,A[ \t]+\{harnessSysPLL/inst/mmcme4_adv_inst/CLKOUT0\}[ \t\r]*$',data,re.M)
            if len(periods)!=1 or abs(Decimal(periods[0].decode())-1000/Decimal(hw['mhz']))>Decimal('0.0005'):
                raise ValueError('wrong or ambiguous routed CPU clock')
    return hw
