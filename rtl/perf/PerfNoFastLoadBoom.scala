package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config
import freechips.rocketchip.devices.debug.{DebugModuleKey, Vcu118BufferDebugSlave}

import freechips.rocketchip.subsystem.{InSubsystem, TilesLocated}
import boom.v3.common.BoomTileAttachParams

// A/B control: the stock Large core and board, changing only speculative load wakeup.
// Disabling speculation may shorten the issue feedback path but cost load-use cycles.
class PerfNoFastLoadBoomVCU118Config extends Config(
  new Config((site, here, up) => {
    case TilesLocated(InSubsystem) => up(TilesLocated(InSubsystem), site).map {
      case tp: BoomTileAttachParams => tp.copy(tileParams = tp.tileParams.copy(
        core = tp.tileParams.core.copy(enableFastLoadUse = false)))
      case other => other
    }
    case DebugModuleKey => up(DebugModuleKey, site).map(_.copy(clockGate = false))
    case Vcu118BufferDebugSlave => true
  }) ++ new WithVCU118Tweaks ++ new chipyard.LargeBoomV3Config)
