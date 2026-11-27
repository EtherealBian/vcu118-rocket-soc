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

# The Medium graph widens TileLink source tags and uses a BoomTile. The
# JTCK launch and IntSync source are identical. Pin each complete tuple;
# do not accept arbitrary combinations of individually recognized modules.
MEDIUM_PINS = dict(PINS, **{
    'DigitalTop': 'b866fa65eab8b5462da1c080164ef33a3131a39a8f21fa470e29dc7bdae2f62d',
    'TLDebugModule': '63a45b2d0f650eed050b6d68b89fc45ab2e150e1c23326c3d98e2aefca5ecf26',
    'TLDebugModuleInner': '07404eaa46944400cb1c62f2c2ff95c81482bec1dc3df0ca15d41d0c508ea888',
    'TLDebugModuleInnerAsync': 'f8f49f8abe8b7cf00b9557304d31bcec8d0a625fa8105c248db1af4b1678509b',
    'TLInterconnectCoupler_cbus_to_debug': '0d563fc455a65602bb39a95bfd05b73fa9d683a0be73482247c9c4f0286cf3d9',
    'TilePRCIDomain': '2c559099c5654ba8b71eb285630f9739d0af93ccc3826b69e75f558c1bf5fd24',
    'BoomTile': '431e7c9221576b8a6c0cac23a4737b96fd1c4076ab05052dabf352282506a925',
    'BoomCore': 'e6b77020ab4c2c1bebc0f57cf505c95e71b0b1585c7556a6b0038ebc3a428bb3',
})

def require_graph(pins, digest):
    for name, expected in pins.items():
        if digest(name) != expected: raise ValueError('unreviewed graph: '+name)

def install(kit):
    def digest(name):
        f = kit/'rtl'/(name+'.sv')
        return hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
    pins = MEDIUM_PINS if (kit/'rtl'/'BoomTile.sv').exists() else PINS
    require_graph(pins, digest)
    leaf = kit/'rtl'/'NonSyncResetSynchronizerPrimitiveShiftReg_d3.sv'
    if leaf.read_bytes().count(b'(* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *)') != 3:
        raise ValueError('marked tile IRQ receiver is required')
    manifest = kit/'sources.f'; rows = manifest.read_text().splitlines(); dest = kit/'rtl'/(NAME+'.sv'); path = dest.relative_to(kit).as_posix()
    if dest.exists() or path in rows or rows.count('rtl/TLDebugModule.sv') != 1: raise ValueError('unexpected HDL manifest')
    top = kit/'rtl'/'TLDebugModule.sv'; new = rewire(top.read_bytes().decode())
    src = Path(__file__).resolve().parents[1]/'rtl'/'clocking'/dest.name
    dest.write_bytes(src.read_bytes().replace(b'\r\n', b'\n')); top.write_bytes(new.encode())
    rows.insert(rows.index('rtl/TLDebugModule.sv'),path); manifest.write_bytes(('\n'.join(rows)+'\n').encode())
