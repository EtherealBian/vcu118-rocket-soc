package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config
import freechips.rocketchip.devices.debug.{DebugModuleKey, Vcu118BufferDebugSlave}

// Same board clocks, ROM interface and memory map, one hart, no accelerator.
// BOOM v3 Medium has a two-wide decoder. 100 MHz is a design target, not Fmax.
class PerfMediumBoomVCU118Config extends Config(
  new Config((site, here, up) => {
    case DebugModuleKey => up(DebugModuleKey, site).map(_.copy(clockGate = false))
    case Vcu118BufferDebugSlave => true
  }) ++ new WithVCU118Tweaks ++ new chipyard.MediumBoomV3Config)
