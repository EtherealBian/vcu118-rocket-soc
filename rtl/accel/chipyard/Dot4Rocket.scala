package chipyard.fpga.vcu118

import org.chipsalliance.cde.config.{Config, Parameters}
import chipyard.vcu118lab.Dot4DigitalTop

class WithVcuDot4 extends Config((site,here,up) => {case chipyard.BuildSystem => (p: Parameters) => new Dot4DigitalTop()(p)})
class Dot4RocketVCU118Config extends Config(new WithVcuDot4 ++ new RocketVCU118Config)
