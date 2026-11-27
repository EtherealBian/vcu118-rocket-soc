// FPGA-only BOOM physical-register-file experiment. Never part of a default kit.
// One private async-read table per write port. The tag chooses the last writer.
// No extra pipeline stage and no reset/initialization of physical registers.
module vcu_lvt_regfile #(
  parameter DATA = 64, ADDR = 7, NR = 12, NW = 6
)(
  input wire clock,
  input wire [NR*ADDR-1:0] raddr, input wire [NR-1:0] ren,
  output wire [NR*DATA-1:0] rdata,
  input wire [NW*ADDR-1:0] waddr, input wire [NW-1:0] wen,
  input wire [NW*DATA-1:0] wdata
);
  localparam TAG = $clog2(NW);
  reg [TAG-1:0] owner[0:(1<<ADDR)-1];
  integer i;
  always @(posedge clock)
    for (i=0; i<NW; i=i+1)
      if (wen[i]) owner[waddr[i*ADDR+:ADDR]] <= i[TAG-1:0];

  wire [DATA*NW-1:0] choices[0:NR-1];
  genvar w,r;
  generate
    for (w=0; w<NW; w=w+1) begin : writer
      (* ram_style = "distributed" *) reg [DATA-1:0] bank[0:(1<<ADDR)-1];
      always @(posedge clock)
        if (wen[w]) bank[waddr[w*ADDR+:ADDR]] <= wdata[w*DATA+:DATA];
      for (r=0; r<NR; r=r+1) begin : read_tap
        assign choices[r][w*DATA+:DATA] = bank[raddr[r*ADDR+:ADDR]];
      end
    end
    for (r=0; r<NR; r=r+1) begin : read_port
      wire [TAG-1:0] chosen = owner[raddr[r*ADDR+:ADDR]];
      wire [DATA-1:0] words[0:NW-1];
      for (w=0; w<NW; w=w+1) begin : pick
        assign words[w] = choices[r][w*DATA+:DATA];
      end
      assign rdata[r*DATA+:DATA] = ren[r] ? words[chosen] : {DATA{1'bx}};
    end
  endgenerate
endmodule
