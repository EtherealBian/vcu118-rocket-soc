// Separate from the frozen CPU-window harness: reuse its off-chip TileLink RAM
// model, not its 100 MHz UART, console, preload path, SD card or JTAG tasks.
#define main archived_chiptop_main
#include "rocket_chiptop.cpp"
#undef main
#ifdef VCU_QUAD_OBSERVER
#include "quad_stage_observer.hpp"
#endif

struct WireRx {
 unsigned period, bit = 0, edges = 0;
 uint64_t next = 0, last = 0;
 bool prev = true, receiving = false;
 unsigned value = 0;
 std::string text;
 explicit WireRx(unsigned p):period(p){}
 void sample(bool level, uint64_t tick) {
  if (level != prev && edges < 10) {
   if (!edges) need(!level, "first edge not a start bit");
   else if (tick-last != period) throw std::runtime_error("UART_EDGE_PERIOD_MISMATCH expected="+std::to_string(period)+" observed="+std::to_string(tick-last));
   ++edges; last=tick; // 'U' = 0x55: start, eight data transitions, stop
  }
  if (!receiving && prev && !level) { receiving=true; next=tick+period/2; bit=value=0; }
  else if (receiving && tick==next) {
   if (!bit) need(!level,"bad start bit");
   else if (bit<=8) value|=unsigned(level)<<(bit-1);
   else { need(level,"bad stop bit"); text.push_back(char(value)); receiving=false; }
   ++bit; next+=period;
  }
  prev=level;
 }
};
int main(int argc,char**argv) { try {
 need(argc==4,"usage: rom_link {100|150|175} frame {single|quad|crc}");
 std::string mhz=argv[1], mode=argv[3];
 need(mhz=="100"||mhz=="150"||mhz=="175","unknown PBUS");
 need(mode=="single"||mode=="quad"||mode=="crc","unknown probe");
 unsigned period=(std::stoul(mhz)*1000000u+57600u)/115200u;
 std::ifstream file(argv[2],std::ios::binary); need(bool(file),"open frame");
 std::vector<unsigned char> bytes{std::istreambuf_iterator<char>(file),{}};
 need(bytes.size()>16 && bytes.size()<=2048,"test fixture size");
 const std::string ready="UART5_READY v1\r\n";
 const std::string expected=ready+(mode=="crc"?"UART5_STOP CRC\r\n":mode=="single"?"UART5_HANDOFF\r\nK":"UART5_HANDOFF\r\nQUAD_ROM_PASS harts=0,1,2,3 turns=64 sum=2080 traps=4\r\n");
 Verilated::commandArgs(argc,argv); VChipTop t; TlMem ram; WireRx rx(period);
 t.custom_boot=0; t.jtag_TMS=1; t.jtag_TDI=0;
 t.spi_0_dq_0_i=0; t.spi_0_dq_1_i=1; t.spi_0_dq_2_i=0; t.spi_0_dq_3_i=0;
 uint64_t start=0, quiet=0, frameTicks=bytes.size()*10ULL*period;
 const uint64_t budget=2000000+frameTicks+10ULL*period*expected.size();
 for (uint64_t i=0;i<budget;++i) {
  t.reset_io=i<100; t.clock_uncore=0; t.jtag_TCK=(i>>3)&1; t.uart_0_rxd=1;
  if (start && i>=start && i-start<frameTicks) {
   auto b=(i-start)/period; unsigned idx=b%10;
   t.uart_0_rxd=idx==9 || (idx && ((bytes[b/10]>>(idx-1))&1));
  }
  ram.drive(t); t.eval(); if (!t.reset_io) ram.sample(t); t.clock_uncore=1; t.eval();
  if (i<128) continue;
  need(t.spi_0_cs_0,"unexpected SD select");
#ifdef VCU_QUAD_OBSERVER
  if (mode=="quad" && start && i>=start+frameTicks) sample_quad(t,i);
#endif
  rx.sample(t.uart_0_txd,i);
  need(expected.compare(0,rx.text.size(),rx.text)==0,"unexpected UART byte");
  if (!start && rx.text==ready) {need(rx.edges==10,"incomplete edge witness"); start=i+2*period;}
  if (rx.text==expected) {
   need(start && i>=start+frameTicks,"premature finish");
   if (!quiet) quiet=i;
   if (i-quiet==20u*period) {
    need(!rx.receiving && ram.reads,"missing idle guard or RAM transaction"); t.final();
    std::cout<<"ROM_LINK_PASS mode="<<mode<<" bit_ticks="<<period<<" edge_intervals=9 frame_bytes="<<bytes.size()<<" cycles="<<i+1<<" quiet_bits=20\n"; return 0;
   }
  }
 }
 throw std::runtime_error("cycle budget expired; decoded bytes="+std::to_string(rx.text.size()));
} catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;} }
