`timescale 1ns/1ps
module tb_probe_protocol;
    reg clk=0,ready=0,rx=1; wire tx;
    always #5 clk=!clk;
    probe_protocol dut(.clk(clk),.ready(ready),.rx(rx),.tx(tx));
    task automatic send_byte(input [7:0] b,input bit stop,input integer bit_ns);
        rx=0; #(bit_ns); for(integer i=0;i<8;i++) begin rx=b[i]; #(bit_ns); end
        rx=stop; #(bit_ns); rx=1;
    endtask
    task automatic get_byte(input [7:0] expected);
        reg [7:0] got; @(negedge tx); #4340; if(tx!==0) $fatal(1,"invalid start");
        for(integer i=0;i<8;i++) begin #8680; got[i]=tx; end
        #8680; if(tx!==1 || got!==expected) $fatal(1,"reply expected=%x got=%x stop=%b",expected,got,tx);
    endtask
    task automatic roundtrip(input [7:0] b,input [7:0] seqno,input integer period);
        fork
            send_byte(b,1,period);
            begin get_byte(8'h56); get_byte(8'h31); get_byte(seqno); get_byte(((b<<3)|(b>>5))^8'ha7); end
        join
        #18000;
    endtask
    initial begin
        #87; ready=1; #1003; rx=0; #1000; rx=1; #20000; // shorter than half a start bit
        send_byte(8'h52,0,8680); #20000;
        if (dut.seqno!==0 || tx!==1) $fatal(1,"bad frame accepted");
        roundtrip(8'h00,0,8520); roundtrip(8'h93,1,8830); roundtrip(8'hff,2,8680);
        send_byte(8'h36,1,8680); #20000; ready=0; #150; if(tx!==1) $fatal(1,"reset during reply");
        ready=1; #2000; roundtrip(8'h5a,0,8680);
        $display("VCU118_PROBE_PROTOCOL_SIM_PASS"); $finish;
    end
    initial begin #5000000; $fatal(1,"timeout waiting for reply"); end
endmodule
