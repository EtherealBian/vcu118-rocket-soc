// SPDX-License-Identifier: MIT
// The two inputs are held levels, not pulses. Only halt_jtck is asynchronous
// to clk. Sample both legs for two destination clocks before combining them.
// The original tile receiver still follows irq. Do not use this as a pulse CDC.
(* KEEP_HIERARCHY = "yes" *) module VcuDebugHaltMerge (
    input wire clk, input wire halt_jtck, input wire halt_on_reset_local,
    output wire irq
);
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) reg halt_meta = 1'b0;
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) reg halt_clean = 1'b0;
    (* SHREG_EXTRACT = "NO" *) reg local_d1 = 1'b0, local_d2 = 1'b0;
    always @(posedge clk) begin
        halt_meta <= halt_jtck;
        halt_clean <= halt_meta;
        local_d1 <= halt_on_reset_local;
        local_d2 <= local_d1;
    end
    assign irq = halt_clean | local_d2;
endmodule
