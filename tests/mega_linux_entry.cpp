// Four-wide ChipTop, genuine ROM frame and privilege transition. Only external
// behavioral TL RAM is preloaded; no internal writes, UART shortcuts or SD.
#define main archived_chiptop_main
#include "rocket_chiptop.cpp"
#undef main
#include "VChipTop___024root.h"
#include <iterator>
#define C(field) (r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__core__DOT__##field)
struct EntryRx {
  unsigned period, edges=0, bit=0, value=0; uint64_t last=0, next=0; bool prev=true, active=false;
  bool sample(bool pin,uint64_t tick,char &out){
    bool got=false;
    if(pin!=prev && edges<10){ if(!edges)need(!pin,"first UART edge"); else need(tick-last==period,"wrong UART bit interval"); ++edges;last=tick; }
    if(!active && prev && !pin){active=true;bit=value=0;next=tick+period/2;}
    else if(active && tick==next){if(!bit)need(!pin,"bad UART start");else if(bit<9)value|=unsigned(pin)<<(bit-1);
      else{need(pin,"bad UART stop");out=char(value);got=true;active=false;} ++bit;next+=period;}
    prev=pin;return got;
  }
};
static std::string bytes(const char* name){std::ifstream f(name,std::ios::binary);need(bool(f),"missing input");return {std::istreambuf_iterator<char>(f),{}};}
int main(int argc,char**argv){try{
  need(argc==4,"usage: entry {valid|crc} raw-fw entry.frame"); std::string mode=argv[1];need(mode=="valid"||mode=="crc","bad mode");
  const auto fw=bytes(argv[2]), frame=bytes(argv[3]);need(fw.size()>0x200040 && fw.size()<0x2000000,"firmware size");
  const unsigned p=1519; const uint32_t base=0x80000000, kentry=0x80200000;
  const std::string ready="UART5_READY v1\r\n", epoch=ready+(mode=="valid"?"UART5_HANDOFF\r\n":"UART5_STOP CRC\r\n");
  need(frame.size()==24&&frame.compare(0,8,"VCU118U5")==0&&frame.substr(16)==fw.substr(0,8),"not the matching entry prefix");
  Verilated::commandArgs(argc,argv);VChipTop t; TlMem ram;const auto &r=*t.rootp;EntryRx rx{p};
  for(size_t j=8;j<fw.size();++j)ram.mem.write(base+j,uint8_t(fw[j]));
  need(!ram.mem.read64(base)&&ram.mem.read64(kentry)==0x00010820106f5a4dULL,"absent entry or Linux Image header");
  t.custom_boot=0;t.jtag_TMS=1;t.jtag_TDI=0;t.spi_0_dq_0_i=0;t.spi_0_dq_1_i=1;t.spi_0_dq_2_i=0;t.spi_0_dq_3_i=0;
  uint64_t send=0,handoff=0,mret=0,kget=0,quiet=0;unsigned retired=0;std::string uart;
  for(uint64_t i=0;i<(mode=="crc"?2000000ULL:80000000ULL);++i){
    t.reset_io=i<100;t.clock_uncore=0;t.jtag_TCK=(i>>3)&1;t.uart_0_rxd=1;
    if(send && i>=send && i-send<24*10u*p){auto b=(i-send)/p;unsigned bit=b%10;t.uart_0_rxd=bit==9||(bit&&((uint8_t(frame[b/10])>>(bit-1))&1));}
    ram.drive(t);t.eval();const unsigned prv=C(csr__DOT__reg_mstatus_prv),mpp=C(csr__DOT__reg_mstatus_mpp);
    const uint64_t epc=C(csr__DOT__reg_mepc); const unsigned vm=C(csr__DOT__reg_satp_mode);const bool ret=C(csr__DOT__insn_ret);
    if(!t.reset_io){
      if(handoff&&!kget&&t.tl_slave_0_a_ready&&t.tl_slave_0_a_valid&&t.tl_slave_0_a_bits_opcode==4&&t.tl_slave_0_a_bits_address==kentry){kget=i;std::cerr<<"KERNEL_ENTRY_TL_GET tick="<<i<<" bytes="<<(1u<<t.tl_slave_0_a_bits_size)<<"\n";}
      if(mret && prv==1 && kget){retired+=C(_rob_io_commit_arch_valids_0)+C(_rob_io_commit_arch_valids_1)+C(_rob_io_commit_arch_valids_2)+C(_rob_io_commit_arch_valids_3);}
      ram.sample(t);
    }
    t.clock_uncore=1;t.eval();if(i<128)continue;need(t.spi_0_cs_0,"unexpected SD select");
    if(prv==3 && C(csr__DOT__reg_mstatus_prv)==1 && epc==kentry && !mret){
      need(mode=="valid"&&ret&&mpp==1&&!vm&&handoff,"invalid kernel privilege handoff");mret=i;std::cerr<<"MRET_KERNEL tick="<<i<<" mepc=0x80200000 prv=3->1 mpp=1 satp_mode=0\n";
    }
    char ch;if(rx.sample(t.uart_0_txd,i,ch)){
      uart+=ch;std::cout.put(ch).flush();need(uart.size()<65536,"unexpected console size");
      if(uart.size()<=epoch.size())need(epoch.compare(0,uart.size(),uart)==0,"incorrect ROM response");
      if(uart==ready){need(!send&&rx.edges==10,"baud witness");send=i+2*p;}
      if(uart==epoch){need(send&&i>=send+24*10u*p,"early ROM exit");quiet=i;
        if(mode=="valid"){handoff=i;uint64_t word=0;for(unsigned j=0;j<8;j++)word|=uint64_t(uint8_t(fw[j]))<<(8*j);
          // The cache may retain dirty entry bytes after the ROM store: verify
          // actual CPU execution with mret, not a read of stale backing memory.
          need(word!=0,"zero entry word");std::cerr<<"ROM_HANDOFF tick="<<i<<" wire=24 backing_preloaded="<<fw.size()-8<<" edge_intervals=9 ticks_per_bit=1519\n";}
      }
    }
    if(mode=="crc" && quiet && i-quiet>=20u*p){need(uart==epoch&&!mret&&!kget&&!rx.active,"CRC path not quiet");t.final();std::cerr<<"BAD_CRC_STOP tick="<<i<<" quiet_bits=20\n";return 0;}
    if(mret&&kget&&retired>=256){t.final();std::cerr<<"ENTRY_WITNESS tick="<<i<<" s_arch_retired="<<retired<<" reads="<<ram.reads<<" writes="<<ram.writes<<"\n";return 0;}
    if(i%5000000==0)std::cerr<<"PROGRESS cycles="<<i<<" reads="<<ram.reads<<" writes="<<ram.writes<<"\n";
  }
  throw std::runtime_error("cycle budget reached without the required witness");
}catch(const std::exception&e){std::cerr<<"ENTRY_FAIL "<<e.what()<<"\n";return 1;}}
