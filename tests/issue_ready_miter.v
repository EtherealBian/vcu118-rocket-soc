// Test both count boundaries against an independent 40-bit population count.
module issue_ready_miter(input wire clk, input wire [39:0] available,
                       output wire [3:0] stock_ready, output wire [3:0] candidate_ready);
  issue_ref a(clk, available, stock_ready);
  issue_partial b(clk, available, candidate_ready);
endmodule
