package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config
import freechips.rocketchip.devices.debug.{DebugModuleKey, Vcu118BufferDebugSlave}

// Four homogeneous, coherent RV64GC Rocket tiles. Same 100 MHz board shell as the reference.
class QuadRocketVCU118Config extends Config(
  new Config((site, here, up) => {
    case DebugModuleKey => up(DebugModuleKey, site).map(_.copy(clockGate = false))
    case Vcu118BufferDebugSlave => true
  }) ++ new WithVCU118Tweaks ++ new chipyard.QuadRocketConfig)
