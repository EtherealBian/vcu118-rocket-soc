  // Static work only until issue. No CSR, RF read, predictor update or other
  // architectural side effect may run early. Carry both exception halves,
  // the predicted branch and the unmodified instruction across every stall.
  val ibuf = Module(new IBuf)
  ibuf.io.imem <> io.imem.resp
  ibuf.io.kill := take_pc
  val deepIssueReady = Wire(Bool())
  val alignValid = RegInit(false.B)
  val decodeValid = RegInit(false.B)
  val decodeReady = !decodeValid || deepIssueReady
  val alignReady = !alignValid || decodeReady
  ibuf.io.inst(0).ready := alignReady && !take_pc
  val fetched = Wire(new Bundle {
    val insn = new Instruction
    val pc = UInt(vaddrBitsExtended.W)
    val btb = new BTBResp
  })
  fetched.insn := ibuf.io.inst(0).bits
  fetched.pc := ibuf.io.pc
  fetched.btb := ibuf.io.btb_resp
  val aligned = RegEnable(fetched, ibuf.io.inst(0).fire)
  val decoded = RegEnable(aligned, alignValid && decodeReady)
  val scalarCtrl = Wire(new IntCtrlSigs).decode(aligned.insn.inst.bits, decode_table)
  // IntCtrlSigs.decode drives scalar fields only; vector legality is decided at issue.
  scalarCtrl.vec := false.B
  val decodedCtrl = RegEnable(scalarCtrl, alignValid && decodeReady)
  when (take_pc) { alignValid := false.B; decodeValid := false.B }
  .otherwise {
    when (alignReady) { alignValid := ibuf.io.inst(0).valid }
    when (decodeReady) { decodeValid := alignValid }
  }
  val deepPending = alignValid || decodeValid
  val deepNextPC = Mux(decodeValid, decoded.pc, Mux(alignValid, aligned.pc, ibuf.io.pc))
  val id_expanded_inst = IndexedSeq(decoded.insn.inst)
  val id_raw_inst = IndexedSeq(decoded.insn.raw)
  val id_inst = id_expanded_inst.map(_.bits)
