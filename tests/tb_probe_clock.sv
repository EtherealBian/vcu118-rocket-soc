`timescale 1ns/1ps
// Board-top regression with AMD's actual behavioral UNISIM MMCME4_BASE + buffers.
// The clock-period assertion refers to simulated time, not metrology on a physical clock.
module tb_probe_clock;
    reg ref_p=0,rx=1; wire tx;
    always #2 ref_p=~ref_p;
    vcu118_probe dut(.sys_clock_p(ref_p),.sys_clock_n(~ref_p),.uart_rxd(rx),.uart_txd(tx));
    task automatic receive(input [7:0] want);
        reg [7:0] got; @(negedge tx); #4340; if(tx!==0) $fatal(1,"start");
        for(integer j=0;j<8;j++) begin #8680; got[j]=tx; end
        #8680; if(tx!==1 || got!==want) $fatal(1,"byte want=%x got=%x stop=%b",want,got,tx);
    endtask
    localparam [7:0] CHALLENGE=8'h36;
    realtime begin_window,periods;
    initial begin
        wait(dut.lock_sync===1'b1); @(posedge dut.clk); begin_window=$realtime;
        repeat (100) @(posedge dut.clk); periods=$realtime-begin_window;
        if(periods<999.9 || periods>1000.1) $fatal(1,"bad simulated fabric clock: %f ns / 100 cycles",periods);
        #1381;
        fork
            begin rx=0;#8680;for(integer j=0;j<8;j++) begin rx=CHALLENGE[j]; #8680; end rx=1;end
            begin receive(8'h56); receive(8'h31); receive(0); receive(8'h16); end // rol(0x36,3)=0xb1
        join
        $display("VCU118_PROBE_UNISIM_PASS window_ns=%0.3f cycles=100",periods); $finish;
    end
    initial begin #2000000; $fatal(1,"timeout waiting for lock or UART"); end
endmodule
