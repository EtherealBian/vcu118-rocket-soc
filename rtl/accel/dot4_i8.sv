`timescale 1ns/1ps
// Four signed int8 products summed into a signed int32. Little lane 0 is bits 7:0.
// Single clock, two elastic stages, one group per cycle when not stalled.
module dot4_i8(input logic clk, input logic rst,
  input logic in_valid, output logic in_ready, input logic [31:0] a,b,
  output logic out_valid, input logic out_ready, output logic signed [31:0] result);
  logic pvalid;
  logic signed [15:0] prod[0:3];
  wire out_open = !out_valid || out_ready;
  assign in_ready = !rst && (!pvalid || out_open);
  function automatic logic signed [31:0] widen(input logic signed [15:0] x);
    return {{16{x[15]}},x};
  endfunction
  always_ff @(posedge clk) begin
    if (rst) begin pvalid<=0; out_valid<=0; result<=0; end
    else begin
      if(out_open) begin
        out_valid<=pvalid;
        if(pvalid) result <= (widen(prod[0])+widen(prod[1]))+(widen(prod[2])+widen(prod[3]));
      end
      if(in_ready) begin
        pvalid<=in_valid;
        if(in_valid) for(int i=0;i<4;i++) prod[i] <= $signed(a[8*i+:8]) * $signed(b[8*i+:8]);
      end
    end
  end
endmodule
