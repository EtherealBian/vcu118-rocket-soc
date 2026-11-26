package chipyard.fpga.vcu118

import chisel3._
import chisel3.util._
import org.chipsalliance.cde.config.{Config, Parameters}
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.prci.{ClockSinkDomain, ClockSinkParameters}
import freechips.rocketchip.regmapper.{RegField, RegWriteFn}
import freechips.rocketchip.subsystem.PBUS
import freechips.rocketchip.tilelink._

// Project-specific optional peripheral. The stock RocketVCU118Config is not changed.
class VcuDot4Primitive extends BlackBox with HasBlackBoxPath {
  override def desiredName = "dot4_i8"
  addPath(sys.env("VCU_DOT4_RTL"))
  val io = IO(new Bundle {
    val clk = Input(Clock()); val rst = Input(Bool())
    val in_valid = Input(Bool()); val in_ready = Output(Bool())
    val a = Input(UInt(32.W)); val b = Input(UInt(32.W))
    val out_valid = Output(Bool()); val out_ready = Input(Bool()); val result = Output(SInt(32.W))
  })
}
class VcuDot4MMIO(beat: Int)(implicit p: Parameters) extends ClockSinkDomain(ClockSinkParameters())(p) {
  val device = new SimpleDevice("dot4", Seq("vcu118lab,dot4-i8-v1"))
  val node = TLRegisterNode(Seq(AddressSet(0x64002000L, 0xfff)), device, "reg/control", beatBytes=beat)
  override lazy val module = new Impl {
    withClockAndReset(clock,reset) {
      val alu = Module(new VcuDot4Primitive)
      val a = RegInit(0.U(32.W)); val b = RegInit(0.U(32.W))
      val pending = RegInit(false.B); val bad = RegInit(false.B)
      val submit = WireDefault(false.B); val consume = WireDefault(false.B)
      alu.io.clk := clock; alu.io.rst := reset.asBool; alu.io.a := a; alu.io.b := b
      alu.io.in_valid := submit; alu.io.out_ready := consume
      val ready = !pending && alu.io.in_ready
      val command = RegWriteFn((valid: Bool, data: UInt) => {
        when(valid) {
          when(data === 1.U && ready) { submit := true.B; pending := true.B }
          .elsewhen(data === 2.U && alu.io.out_valid) { consume := true.B; pending := false.B }
          .elsewhen(data === 4.U) { bad := false.B }
          .otherwise { bad := true.B }
        }
        true.B // even an illegal command cannot hang the CPU/interconnect
      })
      node.regmap(
        0x00 -> Seq(RegField.r(32,"h34544f44".U(32.W))), // little-endian bytes D O T 4 (fixed ABI ID)
        0x04 -> Seq(RegField.r(32,Cat(0.U(28.W),pending,bad,alu.io.out_valid,ready))),
        0x08 -> Seq(RegField(32,a)), 0x0c -> Seq(RegField(32,b)),
        0x10 -> Seq(RegField.w(32,command)), 0x14 -> Seq(RegField.r(32,alu.io.result.asUInt)))
    }
  }
}
class Dot4DigitalTop(implicit p: Parameters) extends chipyard.DigitalTop {
  private val peripheralBus = locateTLBusWrapper(PBUS)
  val dot4 = LazyModule(new VcuDot4MMIO(peripheralBus.beatBytes))
  dot4.clockNode := peripheralBus.fixedClockNode
  peripheralBus.coupleTo("dot4") { dot4.node := TLFragmenter(peripheralBus.beatBytes,peripheralBus.blockBytes) := _ }
}
class WithVcuDot4 extends Config((site,here,up) => {case chipyard.BuildSystem => (p: Parameters) => new Dot4DigitalTop()(p)})
class Dot4RocketVCU118Config extends Config(new WithVcuDot4 ++ new RocketVCU118Config)
