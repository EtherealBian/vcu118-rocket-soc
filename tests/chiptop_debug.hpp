// Testbench-only JTAG Debug Transport. Uses public DMI and abstract-register commands,
// never internal RTL fields. All delays are in simulated 100-MHz uncore cycles.
#include <functional>
struct DebugPort {
 VChipTop &t;std::function<void()> tick;unsigned abits=0;static constexpr int idleclks=12;
 unsigned pulse(bool tms,bool tdi){t.jtag_TMS=tms;t.jtag_TDI=tdi;t.jtag_TCK=0;for(int k=0;k<5;k++)tick();unsigned r=t.jtag_TDO;t.jtag_TCK=1;for(int k=0;k<5;k++)tick();t.jtag_TCK=0;for(int k=0;k<2;k++)tick();return r;}
 void idle(unsigned n){while(n--)pulse(0,0);}
 uint64_t shift(bool ir,unsigned n,uint64_t data){need(n>0&&n<=63,"JTAG length");pulse(1,0);if(ir)pulse(1,0);pulse(0,0);pulse(0,0);uint64_t r=0;for(unsigned i=0;i<n;i++)r|=uint64_t(pulse(i+1==n,(data>>i)&1))<<i;pulse(1,0);pulse(0,0);return r;}
 uint32_t dmi(unsigned a,uint32_t v,unsigned op){uint64_t req=(uint64_t(a)<<34)|(uint64_t(v)<<2)|op;shift(false,abits+34,req);idle(idleclks);auto w=shift(false,abits+34,0);need((w&3)==0,"DMI failed/busy");return uint32_t(w>>2);}
 uint32_t rd(unsigned a){return dmi(a,0,1);}void wr(unsigned a,uint32_t v){dmi(a,v,2);}
 void writeReg(unsigned regno,uint64_t val){wr(4,uint32_t(val));wr(5,uint32_t(val>>32));wr(0x17,(3u<<20)|(1u<<17)|(1u<<16)|regno);uint32_t cs=0;for(unsigned i=0;i<32;i++){cs=rd(0x16);if(!(cs&(1u<<12)))break;}if(cs&0x1700)std::cerr<<"abstract write reg=0x"<<std::hex<<regno<<" abstractcs=0x"<<cs<<std::dec<<"\n";need(!(cs&0x1700),"abstract register write failed");}
 void connectHalt(){for(int i=0;i<8;i++)pulse(1,0);idle(2);shift(true,5,1);auto id=shift(false,32,0);need((id&1)&&id!=0xffffffffu,"JTAG IDCODE");shift(true,5,0x10);auto dtm=shift(false,32,0);abits=(dtm>>4)&63;std::cerr<<"JTAG IDCODE=0x"<<std::hex<<id<<" DTMCS=0x"<<dtm<<std::dec<<"\n";need((dtm&15)==1&&abits>=6&&abits<=10,"unexpected DTMCS");shift(true,5,0x11);wr(0x10,1);wr(0x10,0x80000001);uint32_t status=0;for(unsigned i=0;i<64;i++){status=rd(0x11);if(status&(1u<<9))break;}need(status&(1u<<9),"hart did not halt");wr(0x10,1);
 }
 uint64_t peekDpc(){wr(0x20,0x7b1022f3); /* csrr t0,dpc */ wr(0x21,0x00100073);wr(0x17,1u<<18);syncAbstract();wr(0x17,(3u<<20)|(1u<<17)|0x1005);syncAbstract();return uint64_t(rd(5))<<32|rd(4);}
 void syncAbstract(){uint32_t c=0;for(unsigned k=0;k<32;k++){c=rd(0x16);if(!(c&0x1000))break;}need(!(c&0x1700),"abstract command busy/error");}
 // Diagnostic profile only: sample via the real external JTAG port. The progbuf
 // borrows x5; restore it while still halted before acknowledging resume.
 uint64_t readGpr(unsigned n){wr(0x17,(3u<<20)|(1u<<17)|(0x1000+n));syncAbstract();uint32_t hi=rd(5),lo=rd(4);return (uint64_t(hi)<<32)|lo;}
 uint64_t csrViaScratch(unsigned csr){wr(0x20,(csr<<20)|0x22f3u);wr(0x21,0x00100073);wr(0x17,1u<<18);syncAbstract();return readGpr(5);}
 void resumeHart(){wr(0x10,0x40000001);uint32_t status=0;for(unsigned i=0;i<64;i++){status=rd(0x11);if(status&(1u<<17))break;}need(status&(1u<<17),"hart did not resume");wr(0x10,1);}
 void profile(uint64_t cycle){connectHalt();const uint64_t scratch=readGpr(5);
  std::cerr<<"LINUX_JTAG_SAMPLE cycle="<<cycle<<std::hex;
  for(auto x:{0x7b1u,0x7b0u,0x180u,0x142u,0x141u,0x143u,0x342u,0x341u,0x343u}) {auto v=csrViaScratch(x);std::cerr<<" csr"<<x<<"=0x"<<v;}
  for(auto x:{1u,2u,10u,11u}) {auto v=readGpr(x);std::cerr<<" x"<<std::dec<<x<<"=0x"<<std::hex<<v;}
  writeReg(0x1005,scratch); need(readGpr(5)==scratch,"scratch restoration failed");resumeHart();std::cerr<<std::dec<<" resumed\n";
 }
 void boot(uint64_t entry,uint64_t dtb,bool viaSba=false){connectHalt();uint32_t status=0;
 // Firmware link addresses come from the built payload and the board's ROM symbol.
 writeReg(0x100a,0);writeReg(0x100b,dtb);writeReg(0x1005,entry); /* Rocket supports GPR abstract writes; use progbuf for CSRs. */ wr(0x20,0x7b129073); /* csrw dpc,t0 */ wr(0x21,0x00100073); /* ebreak */ wr(0x17,(1u<<18)); uint32_t cs=0;for(unsigned n=0;n<32;n++){cs=rd(0x16);if(!(cs&0x1000))break;}need(!(cs&0x1700),"setting dpc via progbuf failed");
 wr(0x10,0x40000001);for(unsigned i=0;i<64;i++){status=rd(0x11);if(status&(1u<<17))break;}need(status&(1u<<17),"hart did not resume");wr(0x10,1);std::cerr<<(viaSba?"JTAG_SBA_HANDOFF entry=0x":"JTAG_PRELOADED_HANDOFF entry=0x")<<std::hex<<entry<<" dtb=0x"<<dtb<<std::dec<<" (not SD handoff)\n";
 }
};
