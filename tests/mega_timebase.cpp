// Read-only probes of the sealed stock model. All CPU-visible accesses and
// UART bytes are genuine; only external RAM (excluding entry bytes) is seeded.
#define main archived_chiptop_main
#include "rocket_chiptop.cpp"
#undef main
#include "VChipTop___024root.h"
#include <iterator>
#include <limits>
#define SYS(field) (r.ChipTop__DOT__system__DOT__##field)
#define CL(field) SYS(clint_domain__DOT__clint__DOT__##field)
#define CSR(field) SYS(tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__core__DOT__csr__DOT__##field)
static std::string load(const char* path){std::ifstream f(path,std::ios::binary);need(bool(f),"missing input");return {std::istreambuf_iterator<char>(f),{}};}
int main(int argc,char**argv){try{
  need(argc==4,"usage: timebase entry.bin prefix.frame rx.uart");
  std::ofstream wire(argv[3],std::ios::binary);need(bool(wire),"UART capture unavailable");const auto fw=load(argv[1]),frame=load(argv[2]);
  need(fw.size()>8&&fw.size()<4096&&frame.size()==24&&frame.compare(0,8,"VCU118U5")==0&&frame.substr(16)==fw.substr(0,8),"wrong prefix");
  Verilated::commandArgs(argc,argv);VChipTop t;const auto &r=*t.rootp;TlMem ram;
  for(size_t j=8;j<fw.size();++j)ram.mem.write(0x80000000u+j,uint8_t(fw[j]));
  need(!ram.mem.read64(0x80000000u),"entry already present");t.custom_boot=0;t.jtag_TMS=1;t.jtag_TDI=0;
  t.spi_0_dq_0_i=0;t.spi_0_dq_1_i=1;t.spi_0_dq_2_i=0;t.spi_0_dq_3_i=0;
  constexpr unsigned p=1519;constexpr uint64_t unset=std::numeric_limits<uint64_t>::max();
  const std::string ready="UART5_READY v1\r\n",rom=ready+"UART5_HANDOFF\r\n";
  std::string uart;uint64_t send=0,last=0,first=0,n=0,armed=0,threshold=0,trap=0,disarm=0,ret=0,next=0;bool prev=true,active=false;unsigned bit=0,ch=0;
  for(uint64_t i=0;i<2000000;++i){
    t.reset_io=i<100;t.clock_uncore=0;t.jtag_TCK=(i>>3)&1;t.uart_0_rxd=1;
    if(send&&i>=send&&i-send<frame.size()*10*p){auto b=(i-send)/p;auto k=b%10;t.uart_0_rxd=k==9||(k&&((uint8_t(frame[b/10])>>(k-1))&1));}
    ram.drive(t);t.eval();if(!t.reset_io)ram.sample(t);
    const uint64_t old=CL(time_0),cmp=CL(pad),cause=CSR(reg_mcause);const bool tick=SYS(int_rtc_tick),returning=CSR(insn_ret),mie=CSR(reg_mstatus_mie);
    t.clock_uncore=1;t.eval();if(i<128)continue;need(t.spi_0_cs_0,"unexpected SD access");
    need(CL(time_0)==old+unsigned(tick),"divider/CLINT increment mismatch");
    if(tick){if(last)need(i-last==1000,"wrong CLINT cadence");else first=i;last=i;++n;}
    if(uart.size()>=rom.size()){
      if(cmp!=CL(pad)){
        if(!armed){need(CL(pad)>CL(time_0)&&CL(pad)!=unset,"compare not in future");armed=CL(pad);}
        else {need(!disarm&&trap&&CL(pad)==unset,"unexpected compare disarm");disarm=i;}
      }
      if(armed&&CL(time_0)==armed&&tick){need(!threshold&&!disarm,"bad threshold");threshold=i;}
      if(cause!=CSR(reg_mcause)){need(!trap&&threshold&&mie&&!CSR(reg_mstatus_mie)&&CSR(reg_mcause)==0x8000000000000007ULL,"unexpected machine trap");trap=i;}
      if(trap&&returning){need(!ret&&disarm&&!mie&&CSR(reg_mstatus_mie),"invalid return");ret=i;}
    }
    bool pin=t.uart_0_txd;
    if(!active&&prev&&!pin){active=true;bit=ch=0;next=i+p/2;}
    else if(active&&i==next){if(!bit)need(!pin,"UART start");else if(bit<=8)ch|=unsigned(pin)<<(bit-1);
      else {need(pin,"UART stop");active=false;uart.push_back(char(ch));wire.put(char(ch));
        if(uart.size()<=rom.size())need(rom.compare(0,uart.size(),uart)==0,"ROM mismatch");
        if(uart==ready)send=i+2*p;
        if(uart==rom)need(send&&i>=send+24*10*p,"early handoff");
        if(uart.size()==rom.size()+1)need(ch=='T',"guest diagnostic failed");
        if(uart.size()==rom.size()+10){need(ch=='K'&&first&&n>256&&threshold&&trap>=threshold&&disarm>trap&&ret>=disarm,"missing witness");
          auto word=[&](size_t pos){uint32_t v=0;for(unsigned j=0;j<4;++j)v|=uint32_t(uint8_t(uart[rom.size()+pos+j]))<<(8*j);return v;};
          auto lo=word(1),hi=word(5);need(lo>255744&&lo<=256000&&hi>=256000&&hi<256256,"guest ratio bracket rejected");
          std::cout<<"RTC intervals="<<n-1<<" first="<<first<<" last="<<last<<" period=1000\nGUEST ticks=256 lower="<<lo<<" upper="<<hi<<"\nIRQ compare="<<armed<<" threshold="<<threshold<<" trap="<<trap<<" disarm="<<disarm<<" mret="<<ret<<"\n";
          wire.close();need(bool(wire),"UART capture write failed");t.final();return 0;}
      }++bit;next+=p;}
    prev=pin;
  }throw std::runtime_error("missing guest response before cycle budget");
}catch(const std::exception&e){std::cerr<<"TIMEBASE_FAIL "<<e.what()<<"\n";return 1;}}
