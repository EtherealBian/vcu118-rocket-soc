// Clocked D-cache parent comparison. Only inputs to the exercised paths are
// driven. Address history, store-valid/data registers, flags, selection and
// both parents' lane-1 response formatters execute their original logic.
module tb;
  reg clk=0, rst=0;
  BoomNonBlockingDCache gold(.clock(clk),.reset(rst));
  RetimedDCache gate(.clock(clk),.reset(rst));
  reg [39:0] in0,in1;
  reg valid_in,sgn;
  reg [1:0] sz;
  reg [63:0] data_in, fallback;
  `define DRIVE(u) \
    force u.s1_req_0_addr=in0; force u.s1_req_1_addr=in1; \
    force u._amoalu_io_out=data_in; force u._s3_valid_T=valid_in; \
    force u._s3_valid_T_1=1'b1; force u.s2_sc_fail=1'b0; force u.s2_send_nack_0=1'b0; \
    force u.s2_data_word_prebypass_1={64'h0,fallback}; force u.uncache_respond_1=1'b0; \
    force u.s2_req_1_uop_mem_size=sz; force u.s2_req_1_uop_mem_signed=sgn;
  reg [39:0] prev0,h3,h4,h5;
  reg [63:0] w3,w4,w5,selected,formatted;
  reg [2:0] tags,vals;
  integer edges=0,binary_cases=0,misses=0,x_cases=0,partial=0;
  reg [63:0] mask_coverage=0;
  reg [36:0] one_bit_coverage[0:2];
  localparam [39:0] BASE=40'ha554aa0500;
  localparam [63:0] D3=64'hce719a0f80559933,D4=64'h1f22c36d718045e9,D5=64'h948fbf69d27e681d,F=64'h13ab785c86e29f40;

  task tick(input [39:0] store_in,load_in,input v,input [63:0] d);
    begin
      in0=store_in; in1=load_in; valid_in=v; data_in=d; #2;
      h5=h4; h4=h3; h3=prev0; prev0=in0;
      w5=w4; w4=w3; w3=d; vals={vals[1:0],v};
      tags={h5[39:3]==in1[39:3], h4[39:3]==in1[39:3], h3[39:3]==in1[39:3]};
      selected=(tags[0]&vals[0]) ? w3 : (tags[1]&vals[1]) ? w4 : (tags[2]&vals[2]) ? w5 : fallback;
      clk=1; #2; edges=edges+1;
      if ({gate.vcu_ld1_eq5,gate.vcu_ld1_eq4,gate.vcu_ld1_eq3} !== tags) $fatal(1,"TAG_LATENCY edge=%0d",edges);
      if (gold.s2_data_word_1 !== selected || gate.s2_data_word_1 !== selected) $fatal(1,"FORWARD edge=%0d ref=%h alt=%h expect=%h",edges,gold.s2_data_word_1,gate.s2_data_word_1,selected);
      if (gold.io_lsu_resp_1_bits_data !== gate.io_lsu_resp_1_bits_data) $fatal(1,"RESPONSE_MISMATCH edge=%0d",edges);
      clk=0; #1;
    end
  endtask

  task sample(input [39:0] q,a3,a4,a5,input [2:0] vs,input [63:0] fresh);
    reg [63:0] shifted;
    begin
      tick(a5,~q,1'b0,64'h6917); tick(a4,~q,vs[2],D5); tick(a3,~q,vs[1],D4); tick(~q,q,vs[0],fresh);
      if ((q[2:0] & ((1<<sz)-1))!=0) $fatal(1,"UNALIGNED_ORACLE");
      shifted=selected>>(q[2:0]*8);
      case(sz)
        0: formatted={{56{sgn&shifted[7]}},shifted[7:0]};
        1: formatted={{48{sgn&shifted[15]}},shifted[15:0]};
        2: formatted={{32{sgn&shifted[31]}},shifted[31:0]};
        3: formatted=selected;
      endcase
      if (gold.io_lsu_resp_1_bits_data !== formatted || gate.io_lsu_resp_1_bits_data !== formatted) $fatal(1,"FORMAT edge=%0d",edges);
    end
  endtask

  reg [39:0] q,adr[0:2],diff;
  reg [63:0] fresh;
  reg [2:0] enables;
  integer m,v,i,k,b,j;
  initial begin
    `DRIVE(gold)
    `DRIVE(gate)
    fallback=F;
    for(i=0;i<3;i=i+1) one_bit_coverage[i]=0;
    for(m=0;m<8;m=m+1) for(v=0;v<8;v=v+1) begin
      sz=(m+v)%4; sgn=(m^v)&1; rst=(m==v);
      q=BASE|(((m+2*v)&7)&~((1<<sz)-1));
      for(i=0;i<3;i=i+1) adr[i]=(BASE | ((q[2:0]+i+1)&7)) ^ (((m>>i)&1) ? 40'h0 : (40'h1<<(19+i)));
      sample(q,adr[0],adr[1],adr[2],v,D3);
      if (tags!==m[2:0] || vals!==v[2:0]) $fatal(1,"MASK_COVERAGE");
      mask_coverage[{tags,vals}]=1; binary_cases=binary_cases+1;
    end
    for(k=0;k<3;k=k+1) for(b=3;b<40;b=b+1) begin
      sz=3; sgn=0; q=BASE; rst=0;
      for(i=0;i<3;i=i+1) adr[i]=BASE;
      diff=40'b1<<b; adr[k]=BASE^diff;
      sample(q,adr[0],adr[1],adr[2],3'b001<<k,D3);
      if (selected!==F || (q^adr[k])!==diff || tags[k]!==1'b0) $fatal(1,"SINGLE_BIT");
      one_bit_coverage[k][b-3]=1; misses=misses+1;
    end
    for(j=0;j<6;j=j+1) begin
      q=BASE; adr[0]=BASE; adr[1]=BASE; adr[2]=BASE; fresh=D3; enables=3'b111; sz=3;
      case(j)
        0: adr[0][19]=1'bx;
        1: begin adr[0][19]=1'bx; adr[0][20]=~q[20]; end
        2: enables[0]=1'bx;
        3: adr[0][0]=1'bx;
        4: begin enables[0]=0; enables[1]=1'bx; end
        5: fresh[61]=1'bx;
      endcase
      sample(q,adr[0],adr[1],adr[2],enables,fresh);
      if ((j==0 || j==2 || j==4 || j==5) && ((^selected)!==1'bx || selected === 64'bx)) $fatal(1,"PARTIAL_X");
      if (j==1 && selected!==D4 || j==3 && selected!==D3) $fatal(1,"KNOWN_DESPITE_X");
      if ((^selected)===1'bx && selected !== 64'bx) partial=partial+1;
      x_cases=x_cases+1;
    end
    if ((&mask_coverage)!==1 || (&one_bit_coverage[0])!==1 || (&one_bit_coverage[1])!==1 || (&one_bit_coverage[2])!==1 || partial!=4) $fatal(1,"COVERAGE");
    $display("DCACHE_PASS edges=%0d binary_cases=%0d single_bit_misses=%0d x_cases=%0d partial_x_words=%0d",edges,binary_cases,misses,x_cases,partial); $finish;
  end
  initial #10000 $fatal(1,"WATCHDOG");
endmodule
