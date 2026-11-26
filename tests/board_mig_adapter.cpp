// SPDX-License-Identifier: MIT
// Drive the real board TileLink port. Independently check its D channel and all five AXI channels.
#include "VXilinxVCU118MIG.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
struct Event {uint32_t addr,info; uint64_t data,mask;};
static std::array<std::deque<Event>,5> expected; static unsigned bus[5];
static void need(bool b,const std::string &s){if(!b)throw std::runtime_error(s);}
extern "C" void vcu_bus_seen(int k,unsigned a,unsigned info,unsigned long long data){
 need(k>=0&&k<5&&!expected[k].empty(),"unexpected AXI event "+std::to_string(k)); auto e=expected[k].front(); expected[k].pop_front();
 need(e.addr==a&&e.info==info&&((e.data^data)&e.mask)==0,"AXI address/length/last/strobe/data mismatch, channel="+std::to_string(k)+" address="+std::to_string(a)); ++bus[k];
}
static uint64_t pattern(uint32_t a,unsigned salt){uint64_t x=(uint64_t(a)<<24)^salt^0x65d358fea473190bULL;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);}
static uint64_t lane_mask(unsigned be){uint64_t x=0;for(unsigned i=0;i<8;i++)if((be>>i)&1)x|=255ULL<<(8*i);return x;}
struct Op {unsigned op,sz,id;uint32_t a;std::vector<uint64_t> data;std::vector<unsigned> mask;unsigned d=0;};
struct Run {
 VXilinxVCU118MIG d; unsigned t=0, sys=0, half, phase,sysHalf, stallsA=0,stallsD=0,peak=0,dbeats=0;std::map<uint32_t,uint64_t> mem;
 Run(unsigned h,unsigned p,unsigned sh=3):half(h),phase(p),sysHalf(sh){for(auto &q:expected)need(q.empty(),"old queue");for(auto &n:bus)n=0;d.clock=0;d.io_port_c0_sys_clk_i=0;d.io_port_sys_rst=1;d.io_port_c0_ddr4_aresetn=0;d.reset=1;d.auto_buffer_in_a_valid=0;d.auto_buffer_in_d_ready=0;d.eval();}
 // Return snapshots of the bus handshakes before the active edge, never after RTL has updated.
 struct Seen {bool a=false,dv=false;unsigned id=0,op=0,sz=0;uint64_t data=0;};
 Seen tick(){need(++t<1200000,"watchdog");bool c=(t/sysHalf)&1,ui=((t+phase)/half)&1; bool rise=c&&!d.clock; Seen s;d.eval();
  if(rise){++sys; s.a=d.auto_buffer_in_a_valid&&d.auto_buffer_in_a_ready;s.dv=d.auto_buffer_in_d_valid&&d.auto_buffer_in_d_ready;
   stallsA+=d.auto_buffer_in_a_valid&&!d.auto_buffer_in_a_ready;stallsD+=d.auto_buffer_in_d_valid&&!d.auto_buffer_in_d_ready;
   if(s.dv){need(!d.auto_buffer_in_d_bits_denied&&!d.auto_buffer_in_d_bits_corrupt,"denied/corrupt D");s.id=d.auto_buffer_in_d_bits_source;s.op=d.auto_buffer_in_d_bits_opcode;s.sz=d.auto_buffer_in_d_bits_size;s.data=d.auto_buffer_in_d_bits_data;}
  }d.clock=c;d.io_port_c0_sys_clk_i=ui;d.eval();return s;
 }
 void idle(unsigned n){for(unsigned i=0;i<n;i++)need(!tick().dv,"unsolicited TileLink D");}
 void reset(bool sysFirst){d.auto_buffer_in_a_valid=0;d.auto_buffer_in_d_ready=1;d.reset=1;d.io_port_sys_rst=1;d.io_port_c0_ddr4_aresetn=0;idle(200);
  if(sysFirst)d.reset=0;else d.io_port_sys_rst=0;idle(111);d.reset=0;d.io_port_sys_rst=0;idle(23);d.io_port_c0_ddr4_aresetn=1;idle(250);}
 void batch(unsigned round,unsigned opcode){std::vector<Op> ops; unsigned aop=0,beat=0,done=0,issued=0;std::array<bool,16> started{};
  for(unsigned j=0;j<8;j++){unsigned sz=3+((round+j)%4),n=1u<<(sz-3), id=(j+(round%2)*8);uint32_t base=(j%4==0?0:j%4==1?0x40000000:j%4==2?0x20000000:0x7fff0000)+((round%8)*2+j/4)*4096+(4096-64);
   Op o{opcode,sz,id,base,{},{}};bool read=opcode==4;auto exp=[&](int k,uint32_t a,uint32_t info,uint64_t data=0,uint64_t mask=0){expected[k].push_back({a,info,data,mask});}; exp(read?3:0,base,n);
   for(unsigned i=0;i<n;i++){auto a=base+i*8;unsigned be=opcode==1?(1+((j*43+i*31+round*17)%254)):255;uint64_t data=pattern(a,round*3+opcode+1), mask=lane_mask(be);
    if(read){need(mem.count(a),"reference read before write");data=mem.at(a);exp(4,a,i==n-1,data,~0ULL);}else{exp(1,a,be,data,mask);mem[a]=(mem[a]&~mask)|(data&mask);}
    o.data.push_back(data);o.mask.push_back(be);}
   if(!read)exp(2,base+8*(n-1),0);ops.push_back(o);
  }
  unsigned start=sys;
  while(done<ops.size()){
   d.auto_buffer_in_a_valid=aop<ops.size(); d.auto_buffer_in_d_ready=(sys-start>96)&&((sys%19)>5);
   if(aop<ops.size()){auto &o=ops[aop];d.auto_buffer_in_a_bits_opcode=o.op;d.auto_buffer_in_a_bits_param=0;d.auto_buffer_in_a_bits_source=o.id;d.auto_buffer_in_a_bits_size=o.sz;d.auto_buffer_in_a_bits_address=0x80000000u+o.a;d.auto_buffer_in_a_bits_data=o.data[beat];d.auto_buffer_in_a_bits_mask=o.op==4?255:o.mask[beat];d.auto_buffer_in_a_bits_corrupt=0;}
   auto s=tick();if(s.a){auto &o=ops[aop];if(beat==0){started[o.id]=true;++issued;if(issued-done>peak)peak=issued-done;}if(++beat==(o.op==4?1u:o.data.size())){++aop;beat=0;}}
   if(s.dv){need(started[s.id],"D without a live source");auto &o=ops[s.id%8];need(o.id==s.id&&o.sz==s.sz&&s.op==unsigned(o.op==4),"D source/opcode/size mismatch");
    if(o.op==4)need(o.d<o.data.size()&&o.data[o.d]==s.data,"TL read mismatch");++dbeats;
    if(++o.d==(o.op==4?o.data.size():1u)){started[s.id]=false;++done;}}
  }
  need(aop==ops.size()&&issued==done,"incomplete TL batch");d.auto_buffer_in_a_valid=0;d.auto_buffer_in_d_ready=1;idle(40);for(auto &q:expected)need(q.empty(),"missing AXI events");
 }
 void go(){reset(phase%2);for(unsigned r=0;r<8;r++){batch(r,0);batch(r,4);batch(r,1);batch(r,4);if(r==3)reset(!(phase%2));}idle(150);need(peak>=2&&stallsA&&stallsD&&bus[0]==128&&bus[1]==480&&bus[2]==128&&bus[3]==128&&bus[4]==480&&dbeats==608,"coverage or total mismatch");std::cout<<"MIG_ADAPTER_CASE sys_half="<<sysHalf<<" ui_half="<<half<<" phase="<<phase<<" ticks="<<t<<" AW/W/B/AR/R=128/480/128/128/480 D="<<dbeats<<" TL_A_stalls="<<stallsA<<" TL_D_stalls="<<stallsD<<" peak_outstanding="<<peak<<"\n"; d.final();}
};
int main(int argc,char**argv){Verilated::commandArgs(argc,argv);try{for(unsigned p:{0u,1u,3u})Run(2,p,4).go();for(unsigned h:{2u,3u,7u})for(unsigned p:{0u,1u,3u})Run(h,p).go();std::cout<<"MIG_ADAPTER_MODEL_PASS cases=12 axi_channels=5\n";return 0;}catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}}
