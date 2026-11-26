#!/usr/bin/env python3
"""Build a private nine-stage Rocket candidate from one pinned upstream revision."""
import argparse
from pathlib import Path
from hashlib import sha256


def render(source):
    if sha256(source).hexdigest() != 'de934f129df104cc59f8815a8db3e1f72a17e25ad9a4d9f98181f65e41405957':
        raise ValueError('unreviewed RocketCore revision')
    s=source.decode(); a=s.index('  val ibuf = Module(new IBuf)'); b=s.index('  require(decodeWidth',a)
    tail=s[b:]
    def once(old,new):
        nonlocal tail
        if tail.count(old)!=1:raise ValueError('missing or ambiguous anchor: '+old)
        tail=tail.replace(old,new)
    once('ibuf.io.inst(0).valid || ibuf.io.imem.valid, mem_npc =/= ibuf.io.pc','deepPending || ibuf.io.inst(0).valid || ibuf.io.imem.valid, mem_npc =/= deepNextPC')
    # Protect the one live IBuf reference above while redirecting all issue users.
    once('deepPending || ibuf.io.inst(0).valid','deepPending || RAW_IBUF_VALID')
    once('ibuf.io.inst(0).valid || io.imem.resp.valid','deepPending || RAW_IBUF_VALID || io.imem.resp.valid')
    tail=tail.replace('ibuf.io.inst(0).bits.', 'decoded.insn.').replace('ibuf.io.inst(0).valid','decodeValid').replace('ibuf.io.pc','decoded.pc').replace('ibuf.io.btb_resp','decoded.btb').replace('RAW_IBUF_VALID','ibuf.io.inst(0).valid')
    once('ibuf.io.inst(0).ready := !ctrl_stalld','deepIssueReady := !ctrl_stalld')
    once('val id_ctrl = Wire(new IntCtrlSigs).decode(id_inst(0), decode_table)','val id_ctrl = WireDefault(decodedCtrl)')
    piece=(Path(__file__).resolve().parents[1]/'rtl/multicore/nine-decode.scala.inc').read_text()
    return (s[:a]+piece+'\n'+tail).encode()

def frontend(source):
    if sha256(source).hexdigest() != 'd0a10809d2bf87a58ef35a54f7c2d8969af9381d0bf8cae8ebbb93d62d846a9a':
        raise ValueError('unreviewed Frontend revision')
    old = b'new ShiftQueue(new FrontendResp, 5, flow = true)'
    if source.count(old) != 1:
        raise ValueError('missing fetch boundary')
    return source.replace(old, old.replace(b'true', b'false'))

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('original',type=Path);ap.add_argument('out',type=Path);ap.add_argument('--frontend',action='store_true');x=ap.parse_args(); data=(frontend if x.frontend else render)(x.original.read_bytes());x.out.parent.mkdir(parents=True,exist_ok=True)
    if x.out.exists() and x.out.read_bytes()!=data:raise ValueError('different existing overlay: use a fresh revision directory')
    if not x.out.exists():x.out.write_bytes(data)
    print('QUAD_NINE_SOURCE',sha256(data).hexdigest())
