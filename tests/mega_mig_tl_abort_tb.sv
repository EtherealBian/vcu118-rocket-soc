`timescale 1ps/1ps
module tb;
  integer hs,hd,phase,scenario,do_reset; reg sc=0,ui=0,cause=0,raw=0,armed=0;
  reg inject_bad=0; reg valid=0,accept_d=1,mc_ready=1,data_ready=1;
  reg [31:0] addr; reg [63:0] payload; reg [3:0] src;
  wire sr,ur,sc_out,ready,dvalid,denied,corrupt; wire [2:0] opcode; wire [3:0] dsrc,dsize;
  wire [27:0] mc_addr; wire [2:0] mc_cmd; wire mc_en,mc_w,mc_end; wire [511:0] mc_bits; wire [63:0] mc_mask;
  wire fb_ui,fb_raw;
  ResetWrangler wr(.auto_in_0_clock(sc),.auto_in_0_reset(cause),.auto_in_1_clock(fb_ui),.auto_in_1_reset(fb_raw),
    .auto_out_0_clock(sc_out),.auto_out_0_reset(sr),.auto_out_1_reset(ur));
  XilinxVCU118MIG dut(.clock(sc_out),.reset(sr),.io_port_c0_ddr4_aresetn(~ur),.io_port_c0_sys_clk_i(ui),.io_port_sys_rst(raw),
    .io_port_c0_ddr4_ui_clk(fb_ui),.io_port_c0_ddr4_ui_clk_sync_rst(fb_raw),.auto_buffer_in_a_valid(valid),.auto_buffer_in_a_ready(ready),
    .auto_buffer_in_a_bits_opcode(3'd0),.auto_buffer_in_a_bits_param(3'd0),.auto_buffer_in_a_bits_size(4'd3),
    .auto_buffer_in_a_bits_source(src),.auto_buffer_in_a_bits_address(addr),.auto_buffer_in_a_bits_data(payload ^ {63'd0,inject_bad}),
    .auto_buffer_in_a_bits_mask(8'hff),.auto_buffer_in_a_bits_corrupt(1'b0),.auto_buffer_in_d_ready(accept_d),.auto_buffer_in_d_valid(dvalid),
    .auto_buffer_in_d_bits_opcode(opcode),.auto_buffer_in_d_bits_source(dsrc),.auto_buffer_in_d_bits_size(dsize),
    .auto_buffer_in_d_bits_denied(denied),.auto_buffer_in_d_bits_corrupt(corrupt));
`define IP dut.island.blackbox
  assign {mc_addr,mc_cmd,mc_en,mc_w,mc_end,mc_bits,mc_mask}={`IP.ma,`IP.cmd,`IP.en,`IP.we,`IP.last,`IP.bits,`IP.mask};
  integer a=0,d=0,aw=0,w=0,b=0,cmds=0,datas=0;
  reg [31:0] cmd_epoch [0:3]; reg [31:0] data_epoch [0:3];
  integer raw_aw=0,raw_w=0,raw_b=0;
  always @(posedge sc) if(armed) begin
    if((^{sr,ready,dvalid})===1'bx) $fatal(1,"unknown TL qualifiers");
    if(!sr && ready && valid) a<=a+1;
    if(!sr && dvalid) begin
      if({opcode,dsrc,dsize,denied,corrupt}!=={3'd0,src,4'd3,2'b00}) $fatal(1,"bad D acknowledgment");
      if(accept_d) d<=d+1;
    end
  end
  always @(posedge ui) if(armed) begin
    if((^{ur,mc_en,mc_w,`IP.c0_ddr4_s_axi_awvalid,`IP.c0_ddr4_s_axi_awready,`IP.c0_ddr4_s_axi_wvalid,`IP.c0_ddr4_s_axi_wready,`IP.c0_ddr4_s_axi_bvalid,`IP.c0_ddr4_s_axi_bready})===1'bx) $fatal(1,"unknown pin qualifier");
    if(`IP.c0_ddr4_s_axi_awvalid && `IP.c0_ddr4_s_axi_awready) begin
      if(!ur) begin
        if({`IP.c0_ddr4_s_axi_awaddr,`IP.c0_ddr4_s_axi_awlen,`IP.c0_ddr4_s_axi_awsize}!=={addr[30:0],8'd0,3'd3}) $fatal(1,"bad AW"); aw<=aw+1;
      end else raw_aw<=raw_aw+1;
    end
    if(`IP.c0_ddr4_s_axi_wvalid && `IP.c0_ddr4_s_axi_wready) begin
      if(!ur) begin
        if({`IP.c0_ddr4_s_axi_wdata,`IP.c0_ddr4_s_axi_wstrb,`IP.c0_ddr4_s_axi_wlast}!=={payload,8'hff,1'b1}) $fatal(1,"bad W"); w<=w+1;
      end else raw_w<=raw_w+1;
    end
    if(`IP.c0_ddr4_s_axi_bvalid && `IP.c0_ddr4_s_axi_bready) begin
      if(!ur) begin if(`IP.c0_ddr4_s_axi_bresp!==2'd0) $fatal(1,"bad B"); b<=b+1; end else raw_b<=raw_b+1;
    end
    // Count accepted MC transfers, including during reset. A first-channel transfer need not imply the other happened.
    if(mc_en && mc_ready) begin
      if(mc_cmd!==0 || mc_addr!=={addr[30:6],3'b000}) $fatal(1,"bad app command addr=%h expected=%h cmd=%h",mc_addr,{addr[30:6],3'b000},mc_cmd);
      if(cmds>=3) $fatal(1,"extra MC command"); cmd_epoch[cmds]<=src; cmds<=cmds+1;
    end
    if(mc_w && data_ready) begin
      if({mc_end,mc_mask,mc_bits[63:0]}!=={1'b1,64'hffffffffffffff00,payload}) $fatal(1,"bad app payload/mask: %b %h %h",mc_end,mc_mask,mc_bits[63:0]);
      if(datas>=3) $fatal(1,"extra MC data"); data_epoch[datas]<=src; datas<=datas+1;
    end
  end
  task automatic offer(input [3:0] id,input [31:0] address,input [63:0] value);
    integer prev;
    begin @(negedge sc); src=id; addr=address; payload=value; prev=a; valid=1; wait(a==prev+1); @(negedge sc); valid=0; end
  endtask
  task automatic clean(input [3:0] id,input [31:0] address,input [63:0] value);
    integer a0,d0,aw0,w0,b0,cm0,da0;
    begin a0=a;d0=d;aw0=aw;w0=w;b0=b;cm0=cmds;da0=datas;offer(id,address,value);
      wait(d==d0+1 && cmds==cm0+1 && datas==da0+1); repeat(32) @(negedge sc);
      if(a!=a0+1 || d!=d0+1 || aw!=aw0+1 || w!=w0+1 || b!=b0+1 || cmds!=cm0+1 || datas!=da0+1 || dvalid!==0) $fatal(1,"clean counts");
    end
  endtask
  integer pre_b,pre_dv,pre_cmd,pre_data,held_c,held_w,late_b,off_b,pairs,mixed,n;
  initial begin
    if($test$plusargs("CASE0")) begin hs=2857;hd=2500;phase=113;end
    else if($test$plusargs("CASE1")) begin hs=2857;hd=2500;phase=1569;end
    else if($test$plusargs("CASE2")) begin hs=2500;hd=2857;phase=479;end
    else if($test$plusargs("CASE3")) begin hs=2101;hd=4591;phase=151;end
    else $fatal(1,"missing clocks");
    if($test$plusargs("BLOCKMC")) scenario=0; else if($test$plusargs("PENDACK")) scenario=1;
    else if($test$plusargs("BLOCKCMD")) scenario=2; else if($test$plusargs("BLOCKDATA")) scenario=3; else $fatal(1,"missing mode");
    if($test$plusargs("ABORT")) do_reset=1; else if($test$plusargs("DRAIN")) do_reset=0; else $fatal(1,"missing reset/drain selection");
    fork forever #(hs) sc=~sc; begin #(phase); forever #(hd) ui=~ui; end join_none
    #63; raw=1; cause=1; repeat(8) @(negedge ui); #31; raw=0; repeat(3) @(negedge sc); #51; cause=0;
    wait(sr===0 && ur===0); repeat(32) @(negedge sc); armed=1;
    clean(1,32'h80004000,64'h0123456789abcdef);
    @(negedge ui); mc_ready=(scenario==1 || scenario==3);data_ready=(scenario==1 || scenario==2);accept_d=0;
    offer(2,32'h80008000,64'hfeedcafe5a3cc35a); wait(aw==2 && w==2);
    if(scenario==1) wait(dvalid===1 && cmds==2 && datas==2);
    repeat(32) @(negedge ui); #137; pre_b=b-1;pre_dv=dvalid;pre_cmd=cmds-1;pre_data=datas-1;
    if(a!=2 || d!=1 || aw!=2 || w!=2 || (scenario==0 && (pre_cmd!=0 || pre_data!=0)) ||
       (scenario==1 && (pre_b!=1 || pre_dv!=1 || pre_cmd!=1 || pre_data!=1))) $fatal(1,"missing reset precondition");
    if((scenario==2 && pre_cmd!=0) || (scenario==3 && pre_data!=0) || pre_cmd>1 || pre_data>1) $fatal(1,"invalid split backpressure");
    off_b=b;
    if(do_reset) begin
    cause=1; #17; if({sr,ur,fb_raw}!==3'b110) $fatal(1,"reset wiring"); #783; cause=0;
    repeat(10) @(negedge ui); mc_ready=1; data_ready=1; accept_d=1;
    wait(sr===0 && ur===0); repeat(64) @(negedge sc); repeat(16) @(negedge ui);
    held_c=cmds-1-pre_cmd;held_w=datas-1-pre_data;late_b=b-off_b;
    if(held_c!=0 || held_w!=0 || late_b!=0 || d!=1 || dvalid!==0 || aw!=2 || w!=2) $fatal(1,"late activity after abort %d %d %d /D %d",held_c,held_w,late_b,d);
    end else begin
      @(negedge ui); mc_ready=1;data_ready=1; @(negedge sc);accept_d=1;
      wait(d==2 && cmds==2 && datas==2 && b==2); repeat(40) @(negedge ui);
      if(dvalid!==0 || a!=2 || aw!=2 || w!=2) $fatal(1,"did not drain cleanly");
      held_c=cmds-1-pre_cmd;held_w=datas-1-pre_data;late_b=b-off_b;
    end
    inject_bad=$test$plusargs("BADPAYLOAD");
    clean(3,32'h8000c000,64'hcc7755550099aabb);
    // Non-resetting, in-order application-side consumer hypothesis only. No DDR PHY or memory is present.
    pairs=(cmds<datas)?cmds:datas; mixed=0;
    for(n=0;n<pairs;n=n+1) if(cmd_epoch[n]!==data_epoch[n]) mixed=mixed+1;
    $display("BRIDGE_RESULT abort=%0d scenario=%0d hs=%0d hd=%0d phase=%0d pre_aw=1 pre_w=1 pre_b=%0d pre_dvalid=%0d pre_cmd=%0d pre_data=%0d reset_aw=%0d reset_w=%0d reset_b=%0d late_cmd=%0d late_data=%0d late_b=%0d late_d=%0d clean=2 cmds=%0d datas=%0d fifo_mixed_pairs=%0d",do_reset,scenario,hs,hd,phase,pre_b,pre_dv,pre_cmd,pre_data,raw_aw,raw_w,raw_b,held_c,held_w,late_b,1-do_reset,cmds,datas,mixed); $finish;
  end
  initial #1300000000 $fatal(1,"timeout counts A/D %0d/%0d AW/W/B %0d/%0d/%0d MC %0d/%0d ready %b/%b",a,d,aw,w,b,cmds,datas,mc_ready,data_ready);
endmodule
