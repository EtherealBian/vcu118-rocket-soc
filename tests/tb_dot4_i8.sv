`timescale 1ns/1ps
module tb_dot4_i8;
  bit clk=0; always #5 clk=~clk;
  logic rst=1,in_valid=0,in_ready,out_valid,out_ready=0; logic [31:0] a=0,b=0; logic signed [31:0] result;
  dot4_i8 dut(.*);
  int signed expected[0:4095]; int head=0,tail=0,accepted=0,checked=0,flushed=0,stalls=0,run_len=0,max_run=0;
  bit held=0, input_held=0; logic signed [31:0] frozen; bit [31:0] state=32'h762318ef;
  function automatic int signed gold(input bit [31:0] x,y);
    int signed total,v,w;total=0;
    for(int k=0;k<4;k++) begin v=(x>>(8*k))&255;w=(y>>(8*k))&255; if(v>=128)v-=256; if(w>=128)w-=256; total+=v*w;end
    return total;
  endfunction
  function automatic bit [31:0] step(input bit [31:0] x); x^=x<<13;x^=x>>17;x^=x<<5;return x;endfunction
  always @(posedge clk) begin
    if(rst) begin flushed+=tail-head;head=0;tail=0;held=0;input_held=0;run_len=0;end
    else begin
      if(held && (out_valid!==1 || result!==frozen)) $fatal(1,"output changed while blocked");
      if(out_valid && out_ready) begin
        if(head>=tail || result!==expected[head]) $fatal(1,"bad result idx=%d got=%d ref=%d",head,result,expected[head]);
        head++;checked++;run_len++; if(run_len>max_run)max_run=run_len;
      end else run_len=0;
      if(in_valid && in_ready) begin expected[tail]=gold(a,b);tail++;accepted++;end
      held=out_valid && !out_ready; input_held=in_valid && !in_ready; if(held)begin frozen=result;stalls++;end
    end
  end
  initial begin
    for(int n=0;n<1100;n++)begin
      @(negedge clk); rst=(n==170 || n==702); state=step(state);
      out_ready=(n<64 || n>=1000) ? 1 : ((n>=165 && n<170) ? 0 : state[4]);
      if(!input_held || rst)begin
        in_valid=(n<64 || (n>=160&&n<170)) ? 1 : (n>=1000 ? 0 : state[1]);
        if(n==0)begin a=32'h80808080;b=a;end
        else if(n==1)begin a=32'h80808080;b=32'h7f7f7f7f;end
        else begin state=step(state);a=state;state=step(state);b=state;end
      end
    end
    @(negedge clk); if(checked<200 || flushed<1 || max_run<50 || stalls<100 || tail!=head || accepted!=checked+flushed) $fatal(1,"incomplete coverage");
    $display("DOT4_SIM_PASS accepted=%0d checked=%0d reset_dropped=%0d stalled_cycles=%0d longest_full_rate=%0d",accepted,checked,flushed,stalls,max_run);$finish;
  end
  initial begin #20000;$fatal(1,"timeout");end
endmodule
