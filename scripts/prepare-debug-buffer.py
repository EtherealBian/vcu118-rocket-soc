#!/usr/bin/env python3
"""Create one isolated rocket-chip source override; do not edit a tracked upstream file."""
import argparse,hashlib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('original',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
b=a.original.read_bytes()
if hashlib.sha256(b).hexdigest()!='dc29b17b6a2aa8bcd970778dbc0235eeb4a5f712f4975d871d2ba62c69a53e56':raise ValueError('unexpected upstream Periphery.scala; inspect rather than patch')
s=b.decode(); edits=[('import freechips.rocketchip.tilelink.{TLFragmenter, TLWidthWidget}', 'import freechips.rocketchip.tilelink.{TLBuffer, TLFragmenter, TLWidthWidget}'),
('case object ExportDebug extends Field(DebugAttachParams())','case object ExportDebug extends Field(DebugAttachParams())\ncase object Vcu118BufferDebugSlave extends Field[Boolean](false)'),
('tlDM.node := tlbus.coupleTo("debug"){ TLFragmenter(tlbus.beatBytes, tlbus.blockBytes, nameSuffix = Some("Debug")) := _ }','''tlDM.node := tlbus.coupleTo("debug"){ bus =>
      val fragment = TLFragmenter(tlbus.beatBytes, tlbus.blockBytes, nameSuffix = Some("Debug"))
      fragment := bus
      if (p(Vcu118BufferDebugSlave)) {
        // Two-entry, registered (neither flow nor pipe) queues on A and D.
        val cut = LazyModule(new TLBuffer()).suggestName("vcuDebugSlaveBuffer")
        cut.node := fragment
        cut.node
      } else fragment
    }''')]
for src,dst in edits:
    if s.count(src)!=1:raise ValueError('missing or ambiguous anchor')
    s=s.replace(src,dst)
data=s.encode();a.out.parent.mkdir(parents=True,exist_ok=True)
if a.out.exists():
    if a.out.read_bytes()!=data:raise ValueError('refusing to overwrite differing overlay')
else:a.out.write_bytes(data)
print('PARAMETERIZED_DEBUG_BUFFER_SOURCE',hashlib.sha256(data).hexdigest())
