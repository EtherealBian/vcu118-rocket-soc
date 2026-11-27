// Behavioral check of the *registered OOC boundary*, not the actual CPU latency.
// Replay legal noncolliding writes through the unmodified parent. The integer
// parent bypasses same-address inputs; the floating-point parent does not.
module tb;
  localparam D=`RF_BITS, W=(D==64?6:4), R=(D==64?12:6);
  reg clk=0; reg [7*R-1:0] ra=0; reg [W-1:0] we=0;
  reg [7*W-1:0] wa=0; reg [D*W-1:0] wd=0; wire [D*R-1:0] rd;
  rf_boundary dut(clk,ra,we,wa,wd,rd);
  reg [D-1:0] mem [0:127]; reg [D*R-1:0] expected;
  reg [7*R-1:0] qra=0,sel=0; reg [W-1:0] qwe=0;
  reg [7*W-1:0] qwa=0; reg [D*W-1:0] qwd=0;
  reg [31:0] lo,hi; integer n,i,j,addr,hits=0,changed=0,checks=0;
  initial begin
    for(n=0;n<1024;n=n+1) begin
      // First 128 edges fully initialize every address from multiple writers.
      for(j=0;j<W;j=j+1) begin
        addr=(W*n+j)%128; wa[j*7+:7]=addr;
        we[j]=(n<128)||(((n+3*j)%7)!=0);
        lo=(n+32'h1225)*(j+32'hb85d); hi=(n*32'h47cc0019)^(j*32'h55330607);
        wd[j*D+:D]={((n+j)%2==1),hi,lo};
      end
      for(i=0;i<R;i=i+1) begin
        // Half of the reads collide with next cycle's writes (bypass differs).
        addr=(i%2==0)?(W*(n+1)+(i%W))%128:(19*i+3*n+11)%128;
        ra[i*7+:7]=addr;
      end
      #2;
      for(i=0;i<R;i=i+1) begin
        addr=sel[i*7+:7]; expected[i*D+:D]=mem[addr];
        for(j=0;j<W;j=j+1) if(qwe[j] && qwa[j*7+:7]==addr) begin
          if(n>=130) begin hits=hits+1; if(qwd[j*D+:D]!==mem[addr]) changed=changed+1; end
          if(D==64) expected[i*D+:D]=qwd[j*D+:D];
        end
      end
      for(j=0;j<W;j=j+1) if(qwe[j]) mem[qwa[j*7+:7]]=qwd[j*D+:D];
      sel=qra; qra=ra; qwe=we; qwa=wa; qwd=wd;
      clk=1; #1;
      if(n>=130) for(i=0;i<R;i=i+1) begin
        if((^expected[i*D+:D])===1'bx || rd[i*D+:D]!==expected[i*D+:D])
          begin $display("BOUNDARY_MISMATCH bits=%0d edge=%0d lane=%0d",D,n,i); $stop; end
        checks=checks+1;
      end
      clk=0; #1;
    end
    if(checks!=894*R || changed<894 || hits!=changed) begin $display("insufficient bypass/storage contrast"); $stop; end
    $display("BOUNDARY_PASS bits=%0d edges=1024 lane_checks=%0d same_address_different_data=%0d",D,checks,changed);
    $finish;
  end
endmodule
