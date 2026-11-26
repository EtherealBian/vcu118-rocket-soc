`timescale 1ns/1ps
// SPDX-License-Identifier: MIT
module vcu118_probe(input wire sys_clock_p,sys_clock_n,uart_rxd,output wire uart_txd);
    wire refclk,fb,fb_buf,clk_raw,clk,locked;
    IBUFDS sysibuf(.I(sys_clock_p),.IB(sys_clock_n),.O(refclk));
    MMCME4_BASE #(.CLKIN1_PERIOD(4.000),.DIVCLK_DIVIDE(1),.CLKFBOUT_MULT_F(4.000),
        .CLKOUT0_DIVIDE_F(10.000),.STARTUP_WAIT("FALSE")) mmcm(
        .CLKIN1(refclk),.CLKFBIN(fb_buf),.CLKFBOUT(fb),.CLKOUT0(clk_raw),.LOCKED(locked),.PWRDWN(1'b0),.RST(1'b0));
    BUFG feedback_buf(.I(fb),.O(fb_buf));
    BUFG core_buf(.I(clk_raw),.O(clk));
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg rx_meta=1,rx_sync=1,lock_meta=0,lock_sync=0;
    always @(posedge clk) begin
        rx_meta<=uart_rxd; rx_sync<=rx_meta; lock_meta<=locked; lock_sync<=lock_meta;
    end
    probe_protocol protocol(.clk(clk),.ready(lock_sync),.rx(rx_sync),.tx(uart_txd));
endmodule
