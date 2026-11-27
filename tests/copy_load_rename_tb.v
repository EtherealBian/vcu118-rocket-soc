// Stock and candidate share expanded/decoded instructions and all external inputs.
// Probe the actual physical map, not just the candidate's combinational hit wire.
module tb;
  reg clk,rst,ready,kill,wake; reg [6:0] wp;
  reg [3:0] decfire,disfire,sfb,fault; reg [31:0] ins[0:3];
  wire [3:0] eq,am,bm,astall,bstall;
  wire [6:0] a_prs1[0:3],b_prs1[0:3],a_prs2[0:3],b_prs2[0:3],a_pdst[0:3],b_pdst[0:3],a_stale_pdst[0:3],b_stale_pdst[0:3];
  wire [5:0] a_lrs1[0:3],b_lrs1[0:3];
  wire a_prs1_busy[0:3],b_prs1_busy[0:3],a_prs2_busy[0:3],b_prs2_busy[0:3];
  `include "wiring.svh"
  integer id,i,m,l,src,dst,rd,nhit; reg [3:0] packet;
  reg [6:0] seedp,sourcep,copyp,loadp; reg source_busy,positive;
  function [31:0] alu(input integer d,x,y,f7);
    alu=(f7<<25)|(y<<20)|(x<<15)|(d<<7)|'h33;
  endfunction
  function [31:0] load(input integer d,x,f3,off);
    load=(off<<20)|(x<<15)|(f3<<12)|(d<<7)|3;
  endfunction
  task blank; integer j; begin
    decfire=0;disfire=0;sfb=0;fault=0;ready=1;kill=0;wake=0;wp=0;
    for(j=0;j<4;j=j+1) ins[j]=32'h13;
  end endtask
  task tick; begin #2;clk=1;#2;clk=0;#2;end endtask
  task common(input [3:0] mask,input integer exceptlane); integer j; begin
    #1;
    if(am!==mask || bm!==mask || astall!==bstall || (astall & mask)!==0) $fatal(1,"VALID_OR_STALL case=%0d",id);
    for(j=0;j<4;j=j+1) if(mask[j]) begin
      if(eq[j]!==1) $fatal(1,"OTHER_OUTPUT_CHANGED case=%0d lane=%0d",id,j);
      if(j!=exceptlane && {a_prs1[j],a_prs1_busy[j]}!=={b_prs1[j],b_prs1_busy[j]}) begin
        $display("UNEXPECTED_SOURCE_CHANGE case=%0d lane=%0d",id,j); $finish_and_return(1);
      end
    end
  end endtask
  task expect_load(input [6:0] p,input busy); begin
    if((^p===1'bx) || p==0 || b_prs1[l]!==p || b_prs1_busy[l]!==busy) begin
      $display("SOURCE_ORACLE_MISMATCH case=%0d lane=%0d",id,l); $finish_and_return(1);
    end
  end endtask
  task trial(input integer n); integer j; reg [31:0] mi,li; begin
    id=n; blank; rst=1;tick;tick;rst=0;tick;tick;
    m=(n==1 || n==3) ? 1 : (n==2 || n==20 ? 2 : 0); l=m+1;
    src=n==20 ? 23 : 14; dst=n==20 ? 19 : 8; rd=n==20 ? 6 : src;
    // Give src a real nonzero physical producer; mark it busy first, then optionally wake it.
    ins[0]=(src<<7)|32'h00100013;decfire=1;tick;blank;disfire=1;common(1,-1);
    seedp=a_pdst[0];if(^seedp===1'bx || seedp==0) $fatal(1,"SEED_ALLOC");tick;blank;
    wake=n!=1;wp=seedp;tick;blank;
    mi=alu(dst,0,src,0); li=load(rd,dst,3,0); positive=n<=6 || n>=19;
    if(n==0) begin mi=32'h843a;li=32'h6018;end // actual c.mv x8,x14 and c.ld x14,0(x8)
    case(n)
      8: mi=alu(dst,0,src,32);            // sub, not copy
      9: mi=alu(dst,1,src,0);             // add with nonzero first source
      10: mi=alu(dst,0,0,0);              // zero source excluded
      11: mi=alu(dst,0,dst,0);            // self copy excluded
      12: li=load(rd,17,3,0);             // unrelated base
      13: li=(load(rd,dst,3,0)&32'hffffff80)|7; // FP load
      14: li=(src<<20)|(dst<<15)|(3<<12)|'h23;  // SD
      15: li=(2<<27)|(dst<<15)|(3<<12)|(rd<<7)|'h2f; // LR.D
      16: sfb[m]=1;
      17: sfb[l]=1;
      18: fault[m]=1;
      19: li=load(rd,dst,0,19);           // byte load, nonzero immediate
      20: li=load(rd,dst,2,12);           // unrelated register numbers and destination
      21: begin fault[l]=1;positive=0;end
    endcase
    if(n==3) ins[0]=(src<<7)|32'h00700013; // youngest preceding producer is in this very packet
    ins[m]=mi; ins[l]=li; packet=(1<<(l+1))-1;
    if(n==7) begin // same instruction pair but accepted in two packets
      decfire=1;tick;blank;ins[0]=li;decfire=1;disfire=1;common(1,-1);copyp=a_pdst[0];tick;
      blank;disfire=1;l=0;common(1,-1);expect_load(copyp,1);tick;
    end else begin
      decfire=packet;tick;blank;
      if(n==5) begin ready=0;ins[m]=0;ins[l]=32'hffffffff;tick;tick;blank;end
      disfire=packet;common(packet,positive?l:-1);
      if(positive) begin
        copyp=a_pdst[m];sourcep=n==3 ? a_pdst[0] : seedp;source_busy=n==1 || n==3;
        if(^copyp===1'bx || copyp==0 || copyp==sourcep || a_prs2[m]!==sourcep || a_prs2_busy[m]!==source_busy ||
           a_prs1[l]!==copyp || a_prs1_busy[l]!==1 || a_lrs1[l]!==dst[5:0] || b_lrs1[l]!==dst[5:0]) $fatal(1,"STOCK_ORACLE case=%0d",id);
        expect_load(sourcep,source_busy);loadp=a_pdst[l];
        if(loadp==0 || ^loadp===1'bx || loadp==copyp || loadp==sourcep || (rd==src && a_stale_pdst[l]!==sourcep)) $fatal(1,"ALLOC_STALE case=%0d",id);
        nhit=nhit+1;
      end
      if(n==4) begin // dispatch copy alone, then hold and dispatch the surviving load
        ready=0;disfire=(1<<l)-1;tick;blank;ready=0;tick;blank;disfire=1<<l;
        common(1<<l,l);if(a_prs1[l]!==copyp || a_prs1_busy[l]!==1) $fatal(1,"PARTIAL_STOCK");expect_load(sourcep,source_busy);
      end
      if(n==6) begin // discard packet before either mapping commits at dispatch
        blank;kill=1;tick;blank;common(0,-1);ins[0]=load(src,dst,3,0);decfire=1;tick;blank;disfire=1;common(1,-1);
        if(a_prs1[0]!==0 || a_prs1_busy[0]!==0) $fatal(1,"KILLED_MAP_ESCAPED");
      end
      tick;
    end
    blank;common(0,-1);
  end endtask
  initial begin clk=0;nhit=0;for(i=0;i<22;i=i+1) trial(i);
    if(nhit!=9) $fatal(1,"CASE_COVERAGE"); $display("COPYLOAD_RENAME_PASS cases=22");$finish;end
endmodule
