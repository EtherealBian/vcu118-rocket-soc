// Module-level differential harness. REF_MODULE has the original flat CIRCT ports
// wired by the review script; no reset or random memory init is enabled.
module tb;
  localparam D=`TEST_D, R=`TEST_R, W=`TEST_W;
  reg clk; reg [R*7-1:0] ra; reg [R-1:0] re;
  reg [W*7-1:0] wa; reg [W-1:0] we; reg [W*D-1:0] wd;
  wire [R*D-1:0] original, candidate;
  reference_wrapper reference(clk,ra,re,original,wa,we,wd);
  vcu_lvt_regfile #(.DATA(D),.ADDR(7),.NR(R),.NW(W)) proposed(clk,ra,re,candidate,wa,we,wd);
  reg [D-1:0] shadow[0:127]; reg [D-1:0] expected;
  integer n,i,j,v,checks,edges; reg [31:0] s;
  task step_rng; begin s=s^(s<<13); s=s^(s>>17); s=s^(s<<5); end endtask
  task check;
    begin
      #1;
      for(j=0;j<R;j=j+1) begin
        expected=re[j] ? shadow[ra[7*j+:7]] : {D{1'bx}};
        if(original[j*D+:D] !== expected || candidate[j*D+:D] !== expected) begin
          $display("RF_MISMATCH n=%0d reader=%0d edges=%0d",n,j,edges); $stop;
        end
        checks=checks+1;
      end
    end
  endtask
  task edge_and_check;
    begin
      check; clk=1; edges=edges+1;
      for(i=0;i<W;i=i+1) if(we[i]) shadow[wa[i*7+:7]]=wd[i*D+:D];
      check; clk=0;
    end
  endtask
  task data_words;
    reg [95:0] pack;
    begin for(i=0;i<W;i=i+1) begin
      step_rng;pack[31:0]=s;step_rng;pack[63:32]=s;step_rng;pack[95:64]=s;
      wd[i*D+:D]=pack[D-1:0];
    end end
  endtask
  initial begin
    clk=0; re=0; ra=0; we=0; wa=0; wd=0; n=0; checks=0; edges=0; s=32'h6d2b79f5;
    check; re={R{1'b1}}; check; // unknown before the first write
    for(n=0;n<128;n=n+1) begin // all addresses, all simultaneous-write enable masks
      for(j=0;j<R;j=j+1) ra[7*j+:7]=n;
      for(i=0;i<W;i=i+1) wa[7*i+:7]=n;
      for(v=0;v<(1<<W);v=v+1) begin we=v;data_words;edge_and_check;end
    end
    for(n=0;n<2048;n=n+1) begin
      step_rng;we=s[W-1:0];step_rng;re=s[R-1:0];data_words;
      for(i=0;i<W;i=i+1) begin step_rng;wa[7*i+:7]=(n%3==0)?((n+i)%128):s[6:0];end
      for(j=0;j<R;j=j+1) begin step_rng;ra[7*j+:7]=(j<W)?wa[(j%W)*7+:7]:s[6:0];end
      edge_and_check;
      for(j=0;j<R;j=j+1) begin step_rng;ra[7*j+:7]=s[6:0];end
      check; // asynchronous re-address between active clock edges
    end
    $display("RF_COMPARE_PASS width=%0d readers=%0d writers=%0d edges=%0d lane_checks=%0d",D,R,W,edges,checks);
    $finish;
  end
endmodule
