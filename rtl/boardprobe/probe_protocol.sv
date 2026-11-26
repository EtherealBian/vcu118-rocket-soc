`timescale 1ns/1ps
// SPDX-License-Identifier: MIT
// Independent board fixture: deliberately contains no Rocket, DDR, ROM, or SD logic.
// Host sends one byte then waits for {0x56,0x31,sequence,rol8(request,3)^0xa7}.
module probe_protocol #(parameter integer CLKS_PER_BIT=868) (
    input wire clk, input wire ready, input wire rx, output reg tx=1'b1
);
    localparam N=$clog2(CLKS_PER_BIT);
    localparam IDLE=0, START=1, DATA=2, STOP=3, REARM=4;
    reg [2:0] state=IDLE, rx_index=0;
    reg [N-1:0] rx_ticks=0, tx_ticks=0;
    reg [7:0] sample=0, seqno=0;
    reg [5:0] remaining=0;
    reg [38:0] tail={39{1'b1}};
    function automatic [9:0] frame(input [7:0] val);
        frame={1'b1,val,1'b0};
    endfunction
    always @(posedge clk) begin
        if (!ready) begin
            state<=IDLE; tx<=1; remaining<=0; rx_ticks<=0; tx_ticks<=0; seqno<=0;
        end else begin
            if (remaining!=0) begin
                if (tx_ticks!=0) tx_ticks<=tx_ticks-1'b1;
                else begin
                    tx<=tail[0]; tail<={1'b1,tail[38:1]};
                    tx_ticks<=CLKS_PER_BIT-1; remaining<=remaining-1'b1;
                end
            end
            case (state)
                IDLE: if (!rx) begin state<=START; rx_ticks<=CLKS_PER_BIT/2-1; end
                START: if (rx_ticks!=0) rx_ticks<=rx_ticks-1'b1;
                       else if (rx) state<=IDLE;
                       else begin state<=DATA; rx_index<=0; rx_ticks<=CLKS_PER_BIT-1; end
                DATA: if (rx_ticks!=0) rx_ticks<=rx_ticks-1'b1;
                      else begin
                          sample[rx_index]<=rx; rx_ticks<=CLKS_PER_BIT-1;
                          if (rx_index==7) state<=STOP; else rx_index<=rx_index+1'b1;
                      end
                STOP: if (rx_ticks!=0) rx_ticks<=rx_ticks-1'b1;
                      else if (!rx) state<=REARM;
                      else begin
                          state<=IDLE;
                          if (remaining==0) begin
                              // First start bit is driven immediately; exactly 39 remaining bits and one idle transition.
                              tx<=0; tail<={frame({sample[4:0],sample[7:5]}^8'ha7),frame(seqno),frame(8'h31),1'b1,8'h56};
                              remaining<=40; tx_ticks<=CLKS_PER_BIT-1; seqno<=seqno+1'b1;
                          end
                      end
                default: if (rx) state<=IDLE;
            endcase
        end
    end
endmodule
