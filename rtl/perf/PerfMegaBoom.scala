package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config
import freechips.rocketchip.devices.debug.{DebugModuleKey, Vcu118BufferDebugSlave}

// Same board clocks, ROM interface and memory map, one hart, no accelerator.
// Four-wide / two memory issue slots: timing and useful IPC require separate measurements. 100 MHz is a design target, not Fmax.
class PerfMegaBoomVCU118Config extends Config(
  new Config((site, here, up) => {
    case DebugModuleKey => up(DebugModuleKey, site).map(_.copy(clockGate = false))
    case Vcu118BufferDebugSlave => true
  }) ++ new WithVCU118Tweaks ++ new chipyard.MegaBoomV3Config)
