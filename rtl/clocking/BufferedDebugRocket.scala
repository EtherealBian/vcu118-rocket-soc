package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config
import freechips.rocketchip.devices.debug.Vcu118BufferDebugSlave

// Only this isolated generator jar sees the small parameterized Periphery.scala overlay.
class BufferedDebugRocketVCU118Config extends Config(
  new Config((site, here, up) => { case Vcu118BufferDebugSlave => true }) ++
  new AlwaysClockedDebugRocketVCU118Config)
