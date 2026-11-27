`timescale 1ps/1ps
// Functional DMI handshake boundary, not the serial TAP, an analog CDC model or a board test.
module tb;
  integer hj,hc,ph,stage,abort_tx,corrupt;
  reg jt=0,cpu=0,stopjt=0,common_reset=0,valid=0,resp_ready=0;
  reg [6:0] addr=0; reg [1:0] op=0; reg [31:0] payload=0;
  wire ready,resp_valid,active,ack,jr,release_cpu; wire dr=~release_cpu;
  wire [31:0] respdata; wire [1:0] status;
  localparam [31:0] OLD=32'h963c4ab1, MID=32'ha5c37e19, NEW=32'h52e4c786;
  reg configured=0;
  initial begin
    if ($test$plusargs("CASE0")) begin hj=10000;hc=2857;ph=73;end
    else if ($test$plusargs("CASE1")) begin hj=16667;hc=2857;ph=131;end
    else if ($test$plusargs("CASE2")) begin hj=12500;hc=2857;ph=311;end
    else if ($test$plusargs("CASE3")) begin hj=20000;hc=2857;ph=991;end
    else $fatal(1,"MISSING_CLOCK_CASE"); configured=1;
  end
  initial begin wait(configured); #(ph); forever begin #(hj); if(!stopjt) jt=~jt; end end
  initial begin wait(configured); forever #(hc) cpu=~cpu; end
  ResetCatchAndSync_d3 jreset(.clock(jt),.reset(common_reset),.io_sync_reset(jr));
  AsyncResetSynchronizerShiftReg_w1_d3_i0 dreset(.clock(cpu),.reset(jr),.io_d(1'b1),.io_q(release_cpu));
  ResetSynchronizerShiftReg_w1_d3_i0 active_ack(.clock(cpu),.reset(dr),.io_d(active),.io_q(ack));
  TLDebugModule dut(
    .io_dmi_dmiClock(jt),.io_debug_clock(cpu),.io_tl_clock(cpu),.io_dmi_dmiReset(jr),.io_debug_reset(dr),.io_tl_reset(common_reset),
    .io_hartIsInReset_0(common_reset),.io_ctrl_dmactive(active),.io_ctrl_dmactiveAck(ack),
    .io_dmi_dmi_req_valid(valid),.io_dmi_dmi_req_ready(ready),.io_dmi_dmi_req_bits_addr(addr),.io_dmi_dmi_req_bits_op(op),.io_dmi_dmi_req_bits_data(payload),
    .io_dmi_dmi_resp_valid(resp_valid),.io_dmi_dmi_resp_ready(resp_ready),.io_dmi_dmi_resp_bits_data(respdata),.io_dmi_dmi_resp_bits_resp(status),
    .auto_dmInner_dmInner_sb2tlOpt_out_a_ready(1'b1),.auto_dmInner_dmInner_sb2tlOpt_out_d_valid(1'b0),.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_opcode(3'b0),
    .auto_dmInner_dmInner_sb2tlOpt_out_d_bits_param(2'b0),.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_size(3'b0),.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_sink(4'b0),
    .auto_dmInner_dmInner_sb2tlOpt_out_d_bits_denied(1'b0),.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_data(8'b0),.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_corrupt(1'b0),
    .auto_dmInner_dmInner_tl_in_a_valid(1'b0),.auto_dmInner_dmInner_tl_in_a_bits_opcode(3'b0),.auto_dmInner_dmInner_tl_in_a_bits_size(2'b0),.auto_dmInner_dmInner_tl_in_a_bits_source(11'b0),
    .auto_dmInner_dmInner_tl_in_a_bits_address(12'b0),.auto_dmInner_dmInner_tl_in_a_bits_mask(8'b0),.auto_dmInner_dmInner_tl_in_a_bits_data(64'b0),.auto_dmInner_dmInner_tl_in_d_ready(1'b1));
  wire [31:0] word0={dut.dmInner.dmInner.abstractDataMem_3,dut.dmInner.dmInner.abstractDataMem_2,dut.dmInner.dmInner.abstractDataMem_1,dut.dmInner.dmInner.abstractDataMem_0};
  `define AQ dut.dmOuter.asource.nodeOut_a_source.source_valid_0.io_out_sink_valid_0.output_chain
  `define DQ dut.dmInner.dmiXing.nodeIn_d_source.source_valid_0.io_out_sink_valid_0.output_chain
  wire aclear=`AQ.reset, dclear=`DQ.reset;
  wire [2:0] af={ `AQ.sync_0, `AQ.sync_1, `AQ.sync_2 }, df={ `DQ.sync_0, `DQ.sync_1, `DQ.sync_2 };
  task check_clear;begin if({aclear,dclear}!== {2{jr|dr}}) $fatal(1,"QUEUE_CLEAR_CONE");end endtask
  integer reqs=0,rsps=0,mid_in=0,mid_out=0,mid_inner_d=0,mark=0,je=0,stage_a,stage_d;
  reg [31:0] last;
  always @(posedge jt) begin
    je=je+1;
    if (!jr && valid && ready) reqs=reqs+1;
    if (!jr && resp_valid && resp_ready) begin if(status!==0) $fatal(1,"DMI_ERROR"); rsps=rsps+1; last=respdata; end
    if (!jr && dut.dmOuter.asource.auto_in_a_ready && dut.dmOuter.asource.auto_in_a_valid && dut.dmOuter.asource.auto_in_a_bits_address==9'h10 && dut.dmOuter.asource.auto_in_a_bits_data==MID) mid_in=mid_in+1;
  end
  always @(posedge cpu) begin
    if (!dr && dut.dmInner.dmiXing.auto_out_a_ready && dut.dmInner.dmiXing.auto_out_a_valid && dut.dmInner.dmiXing.auto_out_a_bits_address==9'h10 && dut.dmInner.dmiXing.auto_out_a_bits_data==MID) mid_out=mid_out+1;
    if (mark && !dr && dut.dmInner.dmiXing.auto_out_d_ready && dut.dmInner.dmiXing.auto_out_d_valid) mid_inner_d=mid_inner_d+1;
    if (!dr && dut.auto_dmInner_dmInner_sb2tlOpt_out_a_valid===1'b1) $fatal(1,"UNEXPECTED_SBA");
  end
  task send_req(input [6:0] a,input [1:0] o,input [31:0] v);
    integer first; begin @(negedge jt); first=reqs; addr=a;op=o;payload=v; valid=1; wait(reqs==first+1); #1; valid=0; end
  endtask
  task exchange(input [6:0] a,input [1:0] o,input [31:0] v);
    integer first;begin first=rsps;resp_ready=1;send_req(a,o,v); wait(rsps==first+1);#1;resp_ready=0;end
  endtask
  task activate;begin exchange(7'h10,2,1);repeat(16) @(posedge jt); if(active!==1 || ack!==1) $fatal(1,"DM_NOT_ACTIVE");end endtask
  task roundtrip(input [31:0] v);begin exchange(4,2,v);exchange(4,1,0);if(last!==v || word0!==v) $fatal(1,"DATA0_READBACK");end endtask
  integer baseline,saved_j,i,observed_rsp;
  initial begin
    stage=$test$plusargs("PENDING_RSP"); abort_tx=$test$plusargs("ABORT"); corrupt=$test$plusargs("CORRUPT");
    #23;common_reset=1;repeat(10) @(posedge cpu);#17;common_reset=0;repeat(40) @(posedge jt);activate;roundtrip(OLD);
    mark=1; baseline=rsps;send_req(4,2,MID);wait(mid_in==1);#1;
    if(stage==1) begin wait(resp_valid===1'b1);#1;if(word0!==MID) $fatal(1,"NO_WRITE_BEFORE_RESPONSE");end
    stage_a=mid_out; stage_d=mid_inner_d;check_clear;if(af!==7 || df!==7) $fatal(1,"QUEUE_NOT_WARM");
    if(stage_a!=stage || stage_d!=stage || rsps!=baseline || mid_in!=1) $fatal(1,"WRONG_INTERRUPTION_WINDOW %d %d",stage_a,stage_d);
    stopjt=1; saved_j=je;
    if(abort_tx) begin #29;common_reset=1;#97;check_clear;if(jr!==1 || dr!==1 || af!==0 || df!==0) $fatal(1,"ASYNC_ASSERT");#703;common_reset=0;end
    repeat(20) @(posedge cpu);#3;
    if(saved_j!=je || (abort_tx && (jr!==1 || dr!==1))) $fatal(1,"STOPPED_TCK");
    if(!abort_tx && word0!==MID) $fatal(1,"STALLED_WRITE");
    stopjt=0;
    if(abort_tx) begin
      for(i=1;i<=3;i=i+1) begin @(posedge jt);#1;check_clear;if(jr!==(i<3) || dr!==1 || af!==0 || df!==0) $fatal(1,"JTAG_RELEASE %d",i);end
      for(i=1;i<=3;i=i+1) begin @(posedge cpu);#1;check_clear;if(dr!==(i<3) || af!==0 || df!==0) $fatal(1,"CPU_RELEASE %d",i);end
      fork
        begin : track_a integer k;for(k=1;k<=3;k=k+1)begin @(posedge jt);#1;if(af!==((1<<k)-1)) $fatal(1,"A_VALID_CHAIN");end end
        begin : track_d integer k;for(k=1;k<=3;k=k+1)begin @(posedge cpu);#1;if(df!==((1<<k)-1)) $fatal(1,"D_VALID_CHAIN");end end
      join
      resp_ready=1;repeat(40) @(posedge jt);#1;resp_ready=0;
      if(rsps!=baseline || mid_out!=stage || mid_inner_d!=stage || resp_valid!==0) $fatal(1,"STALE_RESPONSE"); observed_rsp=rsps-baseline;mark=0;activate;
    end else begin
      resp_ready=1;wait(rsps==baseline+1);#1; resp_ready=0;
      if(mid_out!=1 || mid_inner_d!=1) $fatal(1,"CONTROL_DID_NOT_DRAIN");observed_rsp=rsps-baseline;mark=0;exchange(4,1,0); if(last!==MID) $fatal(1,"CONTROL_DATA");
    end
    exchange(4,2,NEW ^ corrupt);exchange(4,1,0);if(last!==NEW || word0!==NEW) $fatal(1,"FRESH_DATA0_READBACK");
    resp_ready=1;baseline=rsps;repeat(64) @(posedge jt);#1;if(rsps!=baseline || mid_in!=1 || mid_out!=(abort_tx?stage:1)) $fatal(1,"UNEXPECTED_REPLAY");
    $display("DMI_CLOCK cpu_half_ps=%0d jtck_half_ps=%0d jtck_phase_ps=%0d",hc,hj,ph);
    $display("DMI_RESULT stage=%0d abort=%0d mid_enqueue=%0d inner_a_at_stop=%0d inner_d_at_stop=%0d final_mid_a=%0d mid_response=%0d fresh_word=%08x",stage,abort_tx,mid_in,stage_a,stage_d,mid_out,observed_rsp,last); $finish;
  end
  initial begin #200000000;$fatal(1,"TIMEOUT req=%0d rsp=%0d mid=%0d/%0d d=%0d active=%b raw=%h",reqs,rsps,mid_in,mid_out,mid_inner_d,active,word0);end
endmodule
