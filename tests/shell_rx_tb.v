`timescale 1ps/1ps
// Only the pad, real AnalogToUInt and shell-to-ChipTop connection are under test.
module shell_rx_tb;
  reg clk=0, pin=1, meta=1, clean=1;
  wire pad; assign pad=pin;
  VCU118FPGATestHarness dut(.uart_rxd(pad));
  integer stages, half_ps, i, phase, a, b, c, checks=0, different=0;
  reg [15:0] rng=16'hb17e;
  task observe;
    reg wanted;
    begin
      wanted=stages==2 ? clean : pin;
      if (dut.chiptop0.uart_0_rxd !== wanted) begin
        $display("RX_LATENCY_MISMATCH sample=%0d expected=%b observed=%b", checks, wanted, dut.chiptop0.uart_0_rxd);
        $finish;
      end
      if (pin!=clean) different=different+1;
      checks=checks+1;
    end
  endtask
  initial begin
    if ($test$plusargs("two_edges")==$test$plusargs("zero_edges") || $test$plusargs("clk175")==$test$plusargs("clk100")) $fatal(1,"missing case");
    stages=$test$plusargs("two_edges") ? 2 : 0; half_ps=$test$plusargs("clk175") ? 2857 : 5000;
    if (!(stages==0||stages==2) || half_ps<8) $fatal(1,"unsupported case");
    force dut._dutWrangler_auto_out_0_clock=clk;
    #1; observe;
    for (i=0;i<256;i=i+1) begin
      // Drive at different distances from both edges, including a one-ps margin.
      phase=i%4; a=phase==0 ? 1 : phase==1 ? half_ps-2 : phase==2 ? half_ps/2 : half_ps/3;
      b=half_ps-a-2; c=half_ps-2;
      #(a); pin=rng[0]; #1; observe;
      #(b); clean=meta; meta=pin; clk=1; #1; observe;
      #1; pin=rng[4]; #1; observe;
      #(c-1); clk=0; #1; observe;
      rng={rng[14:0],rng[15]^rng[13]^rng[12]^rng[10]};

    end
    if (checks!=1025 || different<100) $fatal(1,"vacuous check");
    $display("RX_LATENCY_PASS stages=%0d half_ps=%0d samples=%0d distinguishable=%0d", stages,half_ps,checks,different);
    $finish;
  end
endmodule
