// SPDX-License-Identifier: MIT
// Drive the two reset causes and two clocks of the generated board wrangler.
// Only compare public pins. No PLL/MIG model, no analog recovery/removal model.
#include "VResetWrangler.h"
#include <iostream>
#include <stdexcept>
struct Run {
 VResetWrangler dut; unsigned t=0, good=0, edges[2]={0,0}, releases[2]={0,0}, assertions=0, h1, phase;
 bool seen_reset=false, oldclk[2]={false,false}, oldhold=true, r0=false, r1=false, prev_reset[2]={true,true}, stop0=false, stop1=false;
 Run(unsigned h,unsigned ph):h1(h),phase(ph){dut.auto_in_0_clock=dut.auto_in_1_clock=0;dut.auto_in_0_reset=dut.auto_in_1_reset=0;dut.eval();}
 void step(){
  bool c[2]={!stop0&&((t/3)&1u),!stop1&&(((t+phase)/h1)&1u)};
  bool rise[2]={c[0]&&!oldclk[0],c[1]&&!oldclk[1]}, cause=r0||r1;
  bool hold=oldhold;
  if(cause){good=0;hold=true;seen_reset=true;}
  else if(rise[0]){if(good==10000)hold=false;else ++good;}
  for(int k=0;k<2;++k){if(hold||oldhold)edges[k]=0;else if(rise[k]&&edges[k]<3)++edges[k];}
  dut.auto_in_0_reset=r0;dut.auto_in_1_reset=r1;dut.auto_in_0_clock=c[0];dut.auto_in_1_clock=c[1];dut.eval();
  bool y[2]={bool(dut.auto_out_0_reset),bool(dut.auto_out_1_reset)};
  if(bool(dut.auto_out_0_clock)!=c[0])throw std::runtime_error("clock bypass mismatch");
  for(int k=0;k<2;++k){if(seen_reset&&y[k]!=(edges[k]<3))throw std::runtime_error("debounce/catcher mismatch at tick "+std::to_string(t)+" output "+std::to_string(k));
   if(!y[k]&&prev_reset[k]){if(!rise[k])throw std::runtime_error("asynchronous deassertion");++releases[k];}
   if(y[k]&&!prev_reset[k])++assertions; oldclk[k]=c[k];prev_reset[k]=y[k];}
  oldhold=hold;++t;
 }
 void run(unsigned n){while(n--)step();}
 void pattern(){
  r0=true;run(40);r0=false;run(61000); // both domains release
  r1=true;run(7);stop1=true;r1=false;run(62000); // second clock absent; its reset must stay asserted
  stop1=false;run(150); r0=true;run(5);r1=true;run(4);r0=false;run(8);r1=false;run(59920);
  r1=true;run(5);r1=false;run(61000); // disturbance close to 10,000 edges restarts entire delay
  stop0=true;run(25);r0=true;run(10);r0=false;run(61000);stop0=false;run(62000); // cannot debounce on the wrong clock
  if(releases[0]!=4||releases[1]!=4||assertions!=6)throw std::runtime_error("coverage missing");dut.final();
  std::cout<<"BOARD_WRANGLER_CASE half1="<<h1<<" phase="<<phase<<" release0=4 release1=4 asserted_outputs=6 ticks="<<t<<"\n";
 }
};
int main(){try{for(unsigned h:{2u,5u,7u})for(unsigned p:{0u,1u,3u}){Run r(h,p);r.pattern();}std::cout<<"BOARD_WRANGLER_MODEL_PASS clock_cases=9 debounce_edges=10000 catch_edges=3\n";}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
