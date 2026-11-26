#!/usr/bin/env python3
"""Separate the held halt levels in one pinned buffered/ungated ChipTop kit."""
import hashlib
from pathlib import Path

# Only this generated graph was traced from the two registered launch Qs to
# the tile. A different source, pruning decision, clock, or config needs review.
PINS = {
    'ChipTop': 'f074cdb530c7197a6fe17e473ed72add543ac12276cd631b724afc223e79b0fb',
    'DigitalTop': 'c2b209ef6b100bef80945e86ac00dd459129d2ed85b89ec8085458e8fb440ae9',
    'TLDebugModule': '0adc68fb4600ef00687d814b72d26ba023884bd733d5ca6f506c6b78aa8f7590',
    'TLDebugModuleOuter': '38e8531605fe1833740881ff00da79ac38d0210b3bd9e2f98a01d042e829e243',
    'TLDebugModuleOuterAsync': '9c1db5efbe12650a1e21e3f5fb91101ada9ed67b7d34125ca54ac73d9dc16786',
    'TLDebugModuleInner': '2447161c4c8980565260b5a5acad21fd450cf91b21ff5c8c4e1ec53d32787a68',
    'TLDebugModuleInnerAsync': '711ac84b760a599be3f3ed19db6d71c8b569df45829419e7fea9a55456b2c6db',
    'IntSyncCrossingSource_n1x1_Registered': 'a90a0e00407961b45367fa70541472b11777bcb94089ea8f88dc6d58c55a963e',
    'TLInterconnectCoupler_cbus_to_debug': '763f8c8367380d8dfa30967416827ee12343418b3bed44f0b3324a3d54437253',
}
NAME = 'VcuDebugHaltMerge'

def once(src, before, after):
    if src.count(before) != 1: raise ValueError('missing or ambiguous binding: ' + before)
    return src.replace(before, after)

def rewire(src):
    src = once(src, '  TLDebugModuleOuterAsync dmOuter (', '''  wire vcu_halt_jtck;
  VcuDebugHaltMerge vcu_halt_merge (
    .clk (io_debug_clock), .halt_jtck (vcu_halt_jtck),
    .halt_on_reset_local (_dmInner_io_hgDebugInt_0), .irq (auto_dmOuter_int_out_sync_0)
  );
  TLDebugModuleOuterAsync dmOuter (''')
    src = once(src, '.auto_int_out_sync_0                    (auto_dmOuter_int_out_sync_0)',
                    '.auto_int_out_sync_0                    (vcu_halt_jtck)')
    # Only the OUTER OR input is disconnected; the inner module still drives
    # the same local signal, now going directly to its own registered leg.
    return once(src, '.io_hgDebugInt_0                        (_dmInner_io_hgDebugInt_0)',
                     ".io_hgDebugInt_0                        (1'b0)")

def install(kit):
    for name, expected in PINS.items():
        f = kit/'rtl'/(name+'.sv')
        if hashlib.sha256(f.read_bytes()).hexdigest() != expected: raise ValueError('unreviewed graph: '+name)
    leaf = kit/'rtl'/'NonSyncResetSynchronizerPrimitiveShiftReg_d3.sv'
    if leaf.read_bytes().count(b'(* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *)') != 3:
        raise ValueError('marked tile IRQ receiver is required')
    manifest = kit/'sources.f'; rows = manifest.read_text().splitlines(); dest = kit/'rtl'/(NAME+'.sv'); path = dest.relative_to(kit).as_posix()
    if dest.exists() or path in rows or rows.count('rtl/TLDebugModule.sv') != 1: raise ValueError('unexpected HDL manifest')
    top = kit/'rtl'/'TLDebugModule.sv'; new = rewire(top.read_bytes().decode())
    src = Path(__file__).resolve().parents[1]/'rtl'/'clocking'/dest.name
    dest.write_bytes(src.read_bytes().replace(b'\r\n', b'\n')); top.write_bytes(new.encode())
    rows.insert(rows.index('rtl/TLDebugModule.sv'),path); manifest.write_bytes(('\n'.join(rows)+'\n').encode())
