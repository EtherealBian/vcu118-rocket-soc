package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config
import freechips.rocketchip.devices.debug.{DebugModuleKey, Vcu118BufferDebugSlave}

// Private generator classpath injects the pinned deep RocketCore source overlay.
class Quad150NineRocketVCU118Config extends Config(
  new Config((site, here, up) => {
    case freechips.rocketchip.resources.DTSTimebase => BigInt(150000)
    case freechips.rocketchip.devices.tilelink.BootROMLocated(x) =>
      up(freechips.rocketchip.devices.tilelink.BootROMLocated(x), site).map(_.copy(contentFileName = sys.env("VCU_QUAD_ROM_BIN")))
    case DebugModuleKey => up(DebugModuleKey, site).map(_.copy(clockGate = false))
    case Vcu118BufferDebugSlave => true
  }) ++ new WithFPGAFrequency(150) ++ new WithVCU118Tweaks ++ new chipyard.QuadRocketConfig)
