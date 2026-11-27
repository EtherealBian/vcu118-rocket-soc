`timescale 1ps/1ps
module tb;
  reg clk=0, run_clk=1, ext_rst=0, por=0;
  bit drop_por;
  wire sys_rst = ext_rst | (por & ~drop_por);
  always #2000 if (run_clk) clk = !clk;
  ddr4_v2_2_24_infrastructure #(
    // ACTUAL_PARAMETERS
  ) dut(.sys_clk_in(clk), .mmcm_clk_in(clk), .pll_lock(1'b1), .sys_rst(sys_rst));
  integer edges=0;
  always @(posedge clk) edges++;
  task automatic preset_seen(input integer id);
    if (dut.rst_input_async !== 2'b11) $fatal(1,"PRESET_MISSING case=%0d",id);
  endtask
  task automatic idle_check;
    if ({dut.rst_input_async,dut.rst_input_sync_r,dut.counter_input_rst,dut.input_rst_design,dut.input_rst_mmcm} !== 15'd0)
      $fatal(1,"reset not idle");
  endtask
  // Sample 300 ps after the reference rising edge (configured TCQ = 100 ps).
  // No check uses a DUT-generated reset/clock to advance the stimulus.
  task automatic verify_release(input integer id);
    integer k, start_edges;
    reg [6:0] expected;
    begin
      start_edges=edges;
      for(k=1;k<=57;k++) begin
        @(posedge clk); #300;
        if (sys_rst!==0 || edges!=start_edges+k || dut.rst_input_async!==(k==1 ? 2'b10 : 2'b00)) $fatal(1,"async release mismatch case=%d edge=%d",id,k);
        if (k>=6 && dut.rst_input_sync_r!==0) $fatal(1,"shift release mismatch");
        if (k>=5) begin
          expected=k<=6 ? 50 : k<56 ? 56-k : 0;
          if(dut.counter_input_rst!==expected) $fatal(1,"stretch mismatch case=%d edge=%d count=%d",id,k,dut.counter_input_rst);
        end
        if(k>=6 && dut.input_rst_design!==(k<=56)) $fatal(1,"design reset mismatch case=%d edge=%d",id,k);
        if(k>=7 && dut.input_rst_mmcm!==((k>=47)&&(k<=56))) $fatal(1,"MMCM reset mismatch");
      end
      idle_check(); $display("RESET_RELEASE case=%0d edges=%0d async_clear=2 stretch_last_full=6 design_clear=57",id,edges-start_edges);
    end
  endtask
  integer before_edges;
  initial begin
    drop_por=$test$plusargs("DROP_POR");
    repeat(100) @(negedge clk); #300; idle_check();
    // Short pulse entirely inside a halted-low reference clock interval.
    run_clk=0; before_edges=edges; #700; ext_rst=1; #400; preset_seen(0); #400; ext_rst=0;
    #16000; if(edges!=before_edges || dut.rst_input_async!==3 || dut.input_rst_design!==0) $fatal(1,"halted input did not retain pulse");
    run_clk=1; verify_release(0);
    // POR only: sub-cycle pulse while the reference clock is still running.
    @(negedge clk); #700; por=1; #300; preset_seen(1); #350; por=0; verify_release(1);
    // Overlap sources: dropping the external pin must not release the chain.
    @(negedge clk); #500; ext_rst=1; #300; preset_seen(2); por=1;
    repeat(5) @(negedge clk); #500; ext_rst=0;
    repeat(9) begin @(posedge clk); #300; preset_seen(2); if(dut.input_rst_design!==1) $fatal(1,"lost overlapping reset"); end
    @(negedge clk); #500; por=0; verify_release(2);
    // Cross exactly one rising edge; release 300 ps after it.
    @(negedge clk); #1500; ext_rst=1; #300; preset_seen(3); @(posedge clk); #300; ext_rst=0; verify_release(3);
    // Release during a halt, with the stretcher already fully loaded.
    @(negedge clk); #300; por=1; repeat(12) @(negedge clk); #300; run_clk=0; before_edges=edges; por=0;
    #32000; if(edges!=before_edges || dut.rst_input_async!==3 || dut.input_rst_design!==1 || dut.counter_input_rst!==50) $fatal(1,"halted clock released reset");
    run_clk=1; verify_release(4);
    // Retrigger part-way down the counter and require a fresh release interval.
    @(negedge clk); #300; por=1; #800; por=0; repeat(21) @(posedge clk); #300;
    if (dut.counter_input_rst!==35 || dut.input_rst_design!==1) $fatal(1,"not at retrigger boundary");
    @(negedge clk); #300; ext_rst=1; #400; preset_seen(5); #400; ext_rst=0; verify_release(5);
    $display("MIG_SYSRST_FIXTURE_COMPLETE"); $finish;
  end
  initial begin #10000000; $fatal(1,"watchdog"); end
endmodule
