package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config
import freechips.rocketchip.devices.debug.{DebugModuleKey, Vcu118BufferDebugSlave}
import freechips.rocketchip.devices.tilelink.BootROMLocated
import freechips.rocketchip.resources.DTSTimebase

// A single three-wide RV64 hart, not a four-hart throughput configuration.
// Use a separate class and matched UART ROM so the 100 MHz controls stay intact.
class Perf175LargeBoomVCU118Config extends Config(
  new Config((site, here, up) => {
    case DTSTimebase => BigInt(175000)
    case BootROMLocated(x) => up(BootROMLocated(x), site).map(_.copy(contentFileName = sys.env("VCU_PERF_ROM_BIN")))
    case DebugModuleKey => up(DebugModuleKey, site).map(_.copy(clockGate = false))
    case Vcu118BufferDebugSlave => true
  }) ++ new WithFPGAFrequency(175) ++ new WithVCU118Tweaks ++ new chipyard.LargeBoomV3Config)
