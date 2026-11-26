package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.Config

// Compose the existing MMIO and timing experiments without changing either baseline.
class BufferedDot4RocketVCU118Config extends Config(new WithVcuDot4 ++ new BufferedDebugRocketVCU118Config)
