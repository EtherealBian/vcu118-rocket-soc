package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config
import freechips.rocketchip.devices.debug.DebugModuleKey

// Change only how the debug module is clocked. Keep dmactive/reset semantics,
// JTAG, system-bus access, the program buffer, Rocket and all board clocks.
class WithAlwaysClockedDebug extends Config((site, here, up) => {
  case DebugModuleKey => up(DebugModuleKey, site).map(_.copy(clockGate = false))
})
class AlwaysClockedDebugRocketVCU118Config extends Config(
  new WithAlwaysClockedDebug ++ new RocketVCU118Config)
