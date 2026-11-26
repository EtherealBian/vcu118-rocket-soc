// SPDX-License-Identifier: MIT
// Simulation-only AXI slave replacing just the vendor DDR IP in the generated board adapter.
// The two clock inputs in this test are independent. No PHY, calibration or DDR timing model.
module vcu118mig (
 input c0_sys_clk_i, sys_rst, c0_ddr4_aresetn,
 output wire c0_ddr4_ui_clk, c0_ddr4_ui_clk_sync_rst, c0_init_calib_complete,
 output wire [16:0] c0_ddr4_adr, output wire [1:0] c0_ddr4_ba,
 output wire c0_ddr4_bg,c0_ddr4_reset_n,c0_ddr4_act_n,c0_ddr4_ck_c,c0_ddr4_ck_t,c0_ddr4_cke,c0_ddr4_cs_n,c0_ddr4_odt,
 inout [63:0] c0_ddr4_dq, inout [7:0] c0_ddr4_dqs_c,c0_ddr4_dqs_t,c0_ddr4_dm_dbi_n,
 input [3:0] c0_ddr4_s_axi_awid,c0_ddr4_s_axi_arid, input [30:0] c0_ddr4_s_axi_awaddr,c0_ddr4_s_axi_araddr,
 input [7:0] c0_ddr4_s_axi_awlen,c0_ddr4_s_axi_arlen, input [2:0] c0_ddr4_s_axi_awsize,c0_ddr4_s_axi_arsize,
 input [1:0] c0_ddr4_s_axi_awburst,c0_ddr4_s_axi_arburst, input c0_ddr4_s_axi_awlock,c0_ddr4_s_axi_arlock,
 input [3:0] c0_ddr4_s_axi_awcache,c0_ddr4_s_axi_arcache,c0_ddr4_s_axi_awqos,c0_ddr4_s_axi_arqos,
 input [2:0] c0_ddr4_s_axi_awprot,c0_ddr4_s_axi_arprot, input c0_ddr4_s_axi_awvalid,c0_ddr4_s_axi_arvalid,
 output wire c0_ddr4_s_axi_awready,c0_ddr4_s_axi_arready,
 input [63:0] c0_ddr4_s_axi_wdata, input [7:0] c0_ddr4_s_axi_wstrb, input c0_ddr4_s_axi_wlast,c0_ddr4_s_axi_wvalid,
 output wire c0_ddr4_s_axi_wready, input c0_ddr4_s_axi_bready,c0_ddr4_s_axi_rready,
 output reg [3:0] c0_ddr4_s_axi_bid,c0_ddr4_s_axi_rid, output wire [1:0] c0_ddr4_s_axi_bresp,c0_ddr4_s_axi_rresp,
 output reg c0_ddr4_s_axi_bvalid,c0_ddr4_s_axi_rvalid,c0_ddr4_s_axi_rlast, output reg [63:0] c0_ddr4_s_axi_rdata
);
 import "DPI-C" function void vcu_bus_seen(input int kind, input int unsigned address, input int unsigned info, input longint unsigned data);
 assign c0_ddr4_ui_clk=c0_sys_clk_i, c0_ddr4_ui_clk_sync_rst=sys_rst, c0_init_calib_complete=1'b0;
 assign c0_ddr4_adr='0,c0_ddr4_ba='0,{c0_ddr4_bg,c0_ddr4_reset_n,c0_ddr4_act_n,c0_ddr4_ck_c,c0_ddr4_ck_t,c0_ddr4_cke,c0_ddr4_cs_n,c0_ddr4_odt}='0;
 assign c0_ddr4_s_axi_bresp=0, c0_ddr4_s_axi_rresp=0;
 reg [63:0] ram [int unsigned];
 wire [31:0] keymask=$test$plusargs("fault-alias") ? 32'hbfffffff : 32'hffffffff;
 wire bad_strobe=$test$plusargs("fault-strobe");
 reg wr,rd; reg [31:0] wa,ra; reg [7:0] wl,rl; reg [15:0] lfsr;
 wire run=c0_ddr4_aresetn&&!sys_rst;
 assign c0_ddr4_s_axi_awready=run&&!wr&&!c0_ddr4_s_axi_bvalid&&lfsr[0];
 assign c0_ddr4_s_axi_wready=run&&wr&&lfsr[5];
 assign c0_ddr4_s_axi_arready=run&&!rd&&!c0_ddr4_s_axi_rvalid&&lfsr[3];
 always @(posedge c0_sys_clk_i) begin
  if(!run) begin
   wr<=0;rd<=0;c0_ddr4_s_axi_bvalid<=0;c0_ddr4_s_axi_rvalid<=0;c0_ddr4_s_axi_rlast<=0;lfsr<=16'hc0f1;
  end else begin
   lfsr<={lfsr[14:0],lfsr[15]^lfsr[13]^lfsr[12]^lfsr[10]};
   if(c0_ddr4_s_axi_awvalid&&c0_ddr4_s_axi_awready) begin
    if(c0_ddr4_s_axi_awburst!=1 || c0_ddr4_s_axi_awsize!=3) $fatal(1,"not a full-width INCR write");
    wa<={1'b0,c0_ddr4_s_axi_awaddr};wl<=c0_ddr4_s_axi_awlen;wr<=1;c0_ddr4_s_axi_bid<=c0_ddr4_s_axi_awid;
    vcu_bus_seen(0,{1'b0,c0_ddr4_s_axi_awaddr},32'(c0_ddr4_s_axi_awlen)+1,0);
   end
   if(c0_ddr4_s_axi_wvalid&&c0_ddr4_s_axi_wready) begin
    reg [63:0] word_value; word_value=(ram.exists(wa&keymask)!=0)?ram[wa&keymask]:64'b0;
    for(int i=0;i<8;i++) if(c0_ddr4_s_axi_wstrb[i]||bad_strobe) word_value[8*i+:8]=c0_ddr4_s_axi_wdata[8*i+:8];
    ram[wa&keymask]=word_value; vcu_bus_seen(1,wa,32'(c0_ddr4_s_axi_wstrb),c0_ddr4_s_axi_wdata);
    if(c0_ddr4_s_axi_wlast!=(wl==0)) $fatal(1,"WLAST mismatch");
    if(wl==0) begin wr<=0;c0_ddr4_s_axi_bvalid<=1;end else begin wa<=wa+8;wl<=wl-1;end
   end
   if(c0_ddr4_s_axi_bvalid&&c0_ddr4_s_axi_bready) begin c0_ddr4_s_axi_bvalid<=0;vcu_bus_seen(2,wa,0,0);end
   if(c0_ddr4_s_axi_arvalid&&c0_ddr4_s_axi_arready) begin
    if(c0_ddr4_s_axi_arburst!=1 || c0_ddr4_s_axi_arsize!=3) $fatal(1,"not a full-width INCR read");
    ra<={1'b0,c0_ddr4_s_axi_araddr};rl<=c0_ddr4_s_axi_arlen;rd<=1;c0_ddr4_s_axi_rid<=c0_ddr4_s_axi_arid;
    vcu_bus_seen(3,{1'b0,c0_ddr4_s_axi_araddr},32'(c0_ddr4_s_axi_arlen)+1,0);
   end
   if(rd&&!c0_ddr4_s_axi_rvalid&&lfsr[7]) begin
    if(ram.exists(ra&keymask)==0) $fatal(1,"read of uninitialized AXI word");
    c0_ddr4_s_axi_rdata<=ram[ra&keymask];c0_ddr4_s_axi_rlast<=(rl==0);c0_ddr4_s_axi_rvalid<=1;
   end
   if(c0_ddr4_s_axi_rvalid&&c0_ddr4_s_axi_rready) begin
    vcu_bus_seen(4,ra,32'(c0_ddr4_s_axi_rlast),c0_ddr4_s_axi_rdata); c0_ddr4_s_axi_rvalid<=0;
    if(rl==0) rd<=0;else begin ra<=ra+8;rl<=rl-1;end
   end
  end
 end
endmodule
