// Cycle simulation of the actual generated ChipTop; only off-chip RAM and card are modeled.
// No hierarchical forcing, register pokes, replaced ROM words or UART shortcuts.
#include "VChipTop.h"
#include "verilated.h"
#include <array>
#include <chrono>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
using std::uint8_t;using std::uint16_t;using std::uint32_t;using std::uint64_t;
static void need(bool b,const char *s){if(!b)throw std::runtime_error(s);}
#include "chiptop_address.hpp"
struct Ram {
 uint32_t addressMask=~uint32_t(0);
 std::unordered_map<uint32_t,std::array<uint8_t,4096>> pages;
 uint8_t read(uint32_t a){need(a>=0x80000000u,"offchip read below DDR");a&=addressMask;auto it=pages.find(a>>12);return it==pages.end()?0:it->second[a&4095];}
 void write(uint32_t a,uint8_t v){need(a>=0x80000000u,"offchip write below DDR");a&=addressMask;pages[a>>12][a&4095]=v;}
 uint64_t read64(uint32_t a){uint64_t w=0;for(unsigned i=0;i<8;i++)w|=uint64_t(read(a+i))<<(8*i);return w;}
};
struct TlMem {
 AddressAudit *audit=nullptr;Ram mem;bool dvalid=false,pendingPut=false;unsigned op=0,size=0,src=0,beat=0,beats=0;uint32_t base=0;uint64_t reads=0,writes=0;
 void drive(VChipTop &t){t.tl_slave_0_a_ready=!dvalid;t.tl_slave_0_d_valid=dvalid;t.tl_slave_0_d_bits_opcode=op==4?1:0;t.tl_slave_0_d_bits_param=0;t.tl_slave_0_d_bits_size=size;t.tl_slave_0_d_bits_source=src;t.tl_slave_0_d_bits_sink=0;t.tl_slave_0_d_bits_denied=0;t.tl_slave_0_d_bits_corrupt=0;t.tl_slave_0_d_bits_data=(dvalid&&op==4)?mem.read64((base&~7u)+8*beat):0;}
 void sample(const VChipTop &t){if(t.tl_slave_0_d_valid&&t.tl_slave_0_d_ready){if(op!=4||++beat==beats)dvalid=false;}
  if(!(t.tl_slave_0_a_ready&&t.tl_slave_0_a_valid))return;need(!t.tl_slave_0_a_bits_corrupt,"TL corrupt");
  if(!pendingPut){base=t.tl_slave_0_a_bits_address;size=t.tl_slave_0_a_bits_size;src=t.tl_slave_0_a_bits_source;op=t.tl_slave_0_a_bits_opcode;need(size<=6 && (op==4||op==0||op==1),"TL opcode/size");beats=size<3?1:(1u<<(size-3));beat=0;}else need(t.tl_slave_0_a_bits_source==src&&t.tl_slave_0_a_bits_opcode==op&&t.tl_slave_0_a_bits_address==base,"unstable multibeat TL request");
  if(op==4){if(audit)audit->request(base,op,size);dvalid=true;reads++;return;}for(unsigned i=0;i<8;i++)if((t.tl_slave_0_a_bits_mask>>i)&1)mem.write((base&~7u)+8*beat+i,uint8_t(t.tl_slave_0_a_bits_data>>(8*i)));if(++beat==beats){dvalid=true;pendingPut=false;writes++;if(audit)audit->request(base,op,size);beat=0;}else pendingPut=true;
 }
};
static uint16_t crc16(const uint8_t *p,size_t n){uint16_t c=0;while(n--){c^=uint16_t(*p++)<<8;for(int i=0;i<8;i++)c=(c&0x8000)?(c<<1)^0x1021:c<<1;}return c;}
#include "chiptop_sd.hpp"
struct Uart {
 bool prev=true,recv=false;unsigned bit=0,delay=0;uint8_t val=0;std::string text;static constexpr unsigned period=869;
 void sample(bool tx){if(!recv&&prev&&!tx){recv=true;bit=0;val=0;delay=period+period/2;}else if(recv&&--delay==0){if(bit<8){val|=unsigned(tx)<<bit++;delay=period;}else{need(tx,"UART missing stop bit");text+=char(val);std::cout.put(char(val)).flush();recv=false;}}prev=tx;}
};
// Serial input at the ChipTop boundary. No guest memory patch or host console substitution.
struct SerialSender {
 std::string bytes; unsigned pos=0,bit=0,ticks=0; bool sent=false;
 bool drive(){if(pos==bytes.size())return true;bool v=bit==0?false:(bit==9?true:((uint8_t(bytes[pos])>>(bit-1))&1));if(++ticks==Uart::period){ticks=0;if(++bit==10){bit=0;++pos;}}return v;}
 void shell(){pos=bit=ticks=0;bytes="echo RTL_SHELL_$((40+2))\n";sent=true;}
};
#include "chiptop_debug.hpp"
#include "chiptop_sba.hpp"
#include "chiptop_debug_slave.hpp"
#include "chiptop_recovery.hpp"
int main(int argc,char**argv){try{
 if(argc<3){std::cerr<<"usage: VChipTop media.img debug-slave-lanes|sba-mailbox|sd-prefix|sd-bare|sd-linux|gpt-bare|gpt-badcrc|gpt-linux|debug-bare|debug-linux|debug-dot4|debug-dotbench|gpt-dot4|debug-linux-console|debug-linux-dot4|gpt-linux-dot4|uart5-bare|uart5-dot4|uart5-dotbench|uart5-pack-bare|uart5-pack-badcrc|uart5-address[-mirror29|-mirror30]|uart5-linux|uart5-<fault>|debug-profile-linux [max-cycles] [frame | preload.bin dtb-address]\n";return 2;}
 Verilated::commandArgs(argc,argv);VChipTop t;TlMem ram;Sd sd(argv[1]);Uart uart;SerialSender serial;std::string mode=argv[2];RecoveryFrame recovery(mode,argc,argv);
 AddressAudit addressAudit;bool address=mode=="uart5-address"||mode=="uart5-address-mirror29"||mode=="uart5-address-mirror30";
 bool mirror=address&&mode!="uart5-address";if(address){ram.audit=&addressAudit;if(mirror)ram.mem.addressMask^=1u<<(mode=="uart5-address-mirror29"?29:30);}
 bool candidate=mode.rfind("gpt-",0)==0;std::string reason=mode=="gpt-badcrc"?"PAYLOAD_IO_CRC":mode=="gpt-badheader"?"GPT_HEADER":(mode=="gpt-badtable"||mode=="gpt-bounds")?"GPT_BOUNDS_CRC":"";bool inject=!reason.empty();if(mode=="gpt-badcrc")sd.badLba=34;bool accelBare=mode=="debug-dot4"||mode=="gpt-dot4"||mode=="uart5-dot4";bool accelLinux=mode=="debug-linux-dot4"||mode=="gpt-linux-dot4";bool lanes=mode=="debug-slave-lanes";bool sba=mode=="sba-mailbox";SbaMailbox mailbox;bool profile=mode=="debug-profile-linux";bool interactive=profile||mode=="debug-linux-console"||mode=="uart5-linux"||accelLinux;bool dbg=profile||mode=="debug-dotbench"||mode=="debug-bare"||mode=="debug-linux"||mode=="debug-dot4"||mode=="debug-linux-dot4"||mode=="debug-linux-console";need(lanes||sba||recovery.enabled||dbg||accelBare||accelLinux||mode=="gpt-bare"||mode=="gpt-linux"||inject||mode=="sd-prefix"||mode=="sd-linux"||mode=="sd-bare","unknown mode");uint64_t limit=argc>3?std::stoull(argv[3]):3000000;auto start=std::chrono::steady_clock::now();
 uint64_t dtb=0;if(dbg){need(argc==6,"debug mode requires binary and DTB");dtb=std::stoull(argv[5],nullptr,0);need(dtb>0x10000&&dtb<0x20000,"bad DTB location");std::ifstream f(argv[4],std::ios::binary);need(bool(f),"open preload");char c;uint32_t a=0x80000000u;while(f.get(c)){need(a<0x81e00000,"payload too large");ram.mem.write(a++,uint8_t(c));}need(a>0x80000000u,"empty preload");}
 bool explicitTap=dbg||sba||lanes;bool miso_ff1=true,miso_ff2=true;t.clock_uncore=0;t.reset_io=1;t.uart_0_rxd=1;t.custom_boot=0;t.jtag_TCK=0;t.jtag_TMS=1;t.jtag_TDI=0;t.spi_0_dq_0_i=0;t.spi_0_dq_1_i=1;t.spi_0_dq_2_i=0;t.spi_0_dq_3_i=0;uint64_t cycles=0;
 auto tick=[&](){uint64_t i=cycles++;need(i<limit,"cycle budget expired");t.clock_uncore=0;t.spi_0_dq_1_i=miso_ff2;t.reset_io=i<100;if(interactive||recovery.enabled)t.uart_0_rxd=serial.drive();if(!explicitTap)t.jtag_TCK=(i>>3)&1;ram.drive(t);t.eval();sd.pins(t);if(!t.reset_io)ram.sample(t);miso_ff2=miso_ff1;miso_ff1=sd.miso;t.clock_uncore=1;t.eval();t.spi_0_dq_1_i=miso_ff2;sd.pins(t);uart.sample(t.uart_0_txd);};
 if(lanes){need(argc==4,"debug-slave-lanes takes only a cycle budget");for(unsigned j=0;j<256;j++)tick();DebugPort dp{t,tick};dp.connectHalt();
  // ROM5 runs during TAP acquisition. Its prologue saves ra/s0 below the
  // 0x8ffff000 stack top; the L1 write-allocate fetch is a 64-byte Get.
  std::cerr<<"PREHALT_TL reads="<<ram.reads<<" writes="<<ram.writes<<" opcode="<<ram.op<<" size="<<ram.size<<" address=0x"<<std::hex<<ram.base<<std::dec<<"\n";
  need(ram.reads==1 && !ram.writes && ram.op==4 && ram.size==6 && ram.base==0x8fffefc0 && !ram.dvalid && !ram.pendingPut && sd.cmds.empty(),"unexpected ROM5 pre-halt traffic");
  exerciseDebugSlave(dp); need(sd.cmds.empty() && ram.reads==1 && !ram.writes,"external transaction during debug lane matrix");
  t.final();std::cout<<"ROCKET_RTL_PASS mode=debug-slave-lanes cycles="<<cycles<<" sectors_started=0 prehalt_tl_reads=1 posthalt_tl_reads=0 tl_external_writes=0\n";return 0;}
 if(sba){need(argc==5,"sba-mailbox requires guest image" );for(unsigned j=0;j<256;j++)tick();DebugPort dp{t,tick};mailbox.upload(dp,argv[4]);}
 if(dbg){for(unsigned j=0;j<256;j++)tick();DebugPort jtag{t,tick};jtag.boot(0x80000000,dtb);}
 uint64_t nextProfile=40000000; unsigned profiles=0;
 while(cycles<limit){tick();if(profile&&cycles>=nextProfile&&profiles<12){DebugPort dp{t,tick};dp.profile(cycles);++profiles;nextProfile+=20000000;}
 if(cycles%5000000==0){auto s=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();std::cerr<<"model cycles="<<cycles<<" sectors_started="<<sd.blocks<<" estimated_cycles_per_second="<<long(cycles/s)<<"\n";}
 if((cycles&1023)==0 && (sba||recovery.enabled||dbg||candidate||sd.blocks>=4)){if(!sba&&!dbg&&!candidate&&!recovery.enabled)need(sd.cmds.size()>=7 && sd.firstMulti==34 && uart.text.find("ERROR")==std::string::npos,"ROM error/commands"); if(candidate&&!inject&&uart.text.find("ROM4_STOP")!=std::string::npos)throw std::runtime_error("ROM4 unexpectedly rejected card");bool pass=(mode=="sd-prefix"&&uart.text.find("CMD18")!=std::string::npos)||((mode=="gpt-bare"||mode=="sd-bare"||mode=="debug-bare")&&uart.text.find("VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced")!=std::string::npos)||((mode=="gpt-linux"||mode=="sd-linux"||mode=="debug-linux")&&uart.text.find("SOC_CHECK_PASS bytes=16777216")!=std::string::npos);if(accelBare){need(uart.text.find("DOT4_FAIL")==std::string::npos,"MMIO self-test failed");pass=uart.text.find("DOT4_MMIO_PASS vectors=257 protocol_errors_checked=2\r\n")!=std::string::npos;}
 if(mode=="debug-dotbench"){need(uart.text.find("DOTBENCH_FAIL")==std::string::npos,"MMIO comparison failed");pass=uart.text.find("DOTBENCH_PASS vectors=257 rounds=4\r\n")!=std::string::npos;}
 if(sba&&uart.text.find("\nSBA_GUEST_REPLIED v1\r\n")!=std::string::npos){DebugPort dp{t,tick};mailbox.verify(dp);pass=true;}
 if(interactive){bool soc=uart.text.find("SOC_CHECK_PASS bytes=16777216")!=std::string::npos;bool dot=uart.text.find("LINUX_DOT4_PASS vectors=257 reserved_rejected=1")!=std::string::npos;
  need(uart.text.find("Kernel panic")==std::string::npos&&(!accelLinux||(uart.text.find("LINUX_DOT4_FAILED")==std::string::npos&&uart.text.find("LINUX_DOT4_NO_PLATFORM_DEVICE")==std::string::npos)),"guest failed or accelerator missing");
  if(!serial.sent&&soc&&(!accelLinux||dot)&&uart.text.find("# ")!=std::string::npos)serial.shell();
  pass=serial.sent&&serial.pos==serial.bytes.size()&&(uart.text.find("\nRTL_SHELL_42\r\n")!=std::string::npos||uart.text.find("\nRTL_SHELL_42\n")!=std::string::npos);}
 if(inject&&uart.text.find("ROM4_STOP "+reason+"\r\n")!=std::string::npos){for(unsigned n=0;n<100000;n++)tick();explicitTap=true;DebugPort jtag{t,tick};jtag.connectHalt();uint64_t pc=jtag.peekDpc();std::cerr<<"FAULT_HALT_DPC=0x"<<std::hex<<pc<<std::dec<<"\n";need((pc==0x10038||pc==0x1003c)&&sd.payloadReads==(mode=="gpt-badcrc"?1u:0u)&&uart.text.find("ROM4_HANDOFF")==std::string::npos&&uart.text.find("VCU118_DIAG_START")==std::string::npos,"did not stay in pinned ROM4 error park loop");pass=true;}
 if(recovery.enabled){
  recovery.start(uart,serial); need(sd.cmds.empty(),"serial recovery accessed SD");
  const bool handoff=uart.text.find("UART5_HANDOFF\r\n")!=std::string::npos;
  const bool diag=uart.text.find("VCU118_DIAG_START v1\r\n")!=std::string::npos;
  if(recovery.reason.empty()){
   need(uart.text.find("UART5_STOP")==std::string::npos,"good serial frame was rejected");
   if(mode=="uart5-bare")pass=diag&&uart.text.find("VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced\r\n")!=std::string::npos;
   if(mode=="uart5-dot4")pass=uart.text=="UART5_READY v1\r\nUART5_HANDOFF\r\nDOT4_MMIO_START\r\nDOT4_MMIO_PASS vectors=257 protocol_errors_checked=2\r\n";
   if(mode=="uart5-pack-bare"||mode=="uart5-pack-badcrc"){
    const std::string epoch="UART5_READY v1\r\nUART5_HANDOFF\r\n";
    const std::string ok="UART5_PACK1_OK bytes=422 crc32=e6f03e5e\r\nVCU118_DIAG_START v1\r\nVCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced\r\n";
    if(mode=="uart5-pack-bare"){need(uart.text.find("UART5_PACK1_STOP")==std::string::npos,"packed stage rejected good fixture");pass=uart.text==epoch+ok;}
    else {need(uart.text.find("VCU118_DIAG_START")==std::string::npos && uart.text.find("UART5_PACK1_OK")==std::string::npos,"bad inner CRC executed");pass=uart.text==epoch+"UART5_PACK1_STOP\r\n";
     if(pass){for(unsigned j=0;j<200000;j++)tick();need(uart.text==epoch+"UART5_PACK1_STOP\r\n"&&sd.cmds.empty(),"bad packed image did not stay silent");}}
   }
   if(mode=="uart5-dotbench"){
    need(uart.text.find("DOTBENCH_FAIL")==std::string::npos,"dot comparison failed");
    const std::string begin="UART5_READY v1\r\nUART5_HANDOFF\r\nDOTBENCH_START v1 vectors=257\r\n";
    pass=uart.text.rfind(begin,0)==0 && uart.text.find("\r\nDOTBENCH_PASS vectors=257 rounds=4\r\n")!=std::string::npos;
   }
   if(address){bool start=uart.text.find("VCU118_ADDR_START v1\r\n")!=std::string::npos;
    bool good=uart.text.find("VCU118_ADDR_PASS windows=4 bytes_each=4096 passes=2 flush_lines=512\r\n")!=std::string::npos;
    bool bad=uart.text.find("VCU118_ADDR_FAIL data\r\n")!=std::string::npos;
    need(uart.text.find("VCU118_ADDR_FAIL cache-config")==std::string::npos && !(mirror?good:bad),"unexpected address test outcome");
    pass=start&&(mirror?bad:good);if(pass&&!mirror)addressAudit.verify();}
   pass=pass&&handoff&&recovery.started&&serial.pos==serial.bytes.size();
  }else{
   need(!handoff&&!diag,"invalid frame executed");
   pass=uart.text.find("UART5_STOP "+recovery.reason+"\r\n")!=std::string::npos;
   if(pass){need(recovery.started&&serial.pos==serial.bytes.size(),"failure before full fixture");for(unsigned n=0;n<10000;n++)tick();explicitTap=true;DebugPort dp{t,tick};dp.connectHalt();auto pc=dp.peekDpc();need(pc==0x10038||pc==0x1003c,"hart not parked in ROM5");std::cerr<<"UART5_HALT_DPC=0x"<<std::hex<<pc<<std::dec<<"\n";}
  }
 }
 if(pass){if(candidate&&!inject){need(uart.text.find("ROM4_HANDOFF")!=std::string::npos,"missing clean handoff");if(mode=="gpt-bare")need(sd.payloadReads==1,"compact bare was not exactly one data sector");}std::cout<<"\nROCKET_RTL_PASS mode="<<mode<<" cycles="<<cycles<<" sectors_started="<<sd.blocks<<" tl_read_transactions="<<ram.reads<<" tl_write_transactions="<<ram.writes<<" (behavioral RAM/card, no physical DDR)\n";t.final();return 0;}}}
 std::cerr<<"timeout sectors="<<sd.blocks<<" TL reads="<<ram.reads<<" writes="<<ram.writes<<"\n";return 1;}catch(const std::exception&e){std::cerr<<"RTL TEST FAIL: "<<e.what()<<"\n";return 1;}}
