// Serial-only boot fixture. Do not preload memory or use JTAG on a success path.
#include <iterator>
struct RecoveryFrame {
 bool enabled=false, started=false; std::string data, reason;
 RecoveryFrame(const std::string &mode, int argc, char** argv) {
  if (mode.rfind("uart5-",0)!=0) return;
  enabled=true;
  if(mode=="uart5-badcrc") reason="CRC";
  else if(mode=="uart5-badmagic") reason="MAGIC";
  else if(mode=="uart5-badlength") reason="LENGTH";
  else if(mode=="uart5-truncated") reason="TIMEOUT";
  else need(mode=="uart5-bare"||mode=="uart5-dot4"||mode=="uart5-dotbench"||mode=="uart5-linux"||mode=="uart5-address"||mode=="uart5-address-mirror29"||mode=="uart5-address-mirror30", "unknown UART5 case");
  need(argc==5,"uart5 mode requires prepared frame path after cycle limit");
  std::ifstream f(argv[4],std::ios::binary); need(bool(f),"frame not found");
  data.assign(std::istreambuf_iterator<char>(f),{});
  need(!data.empty() && data.size()<=16u+(30u<<20),"fixture size invalid");
 }
 void start(const Uart &uart,SerialSender &sender){
  if(!started && uart.text.find("UART5_READY v1\r\n")!=std::string::npos){
   sender.bytes.swap(data); started=true;
  }
 }
};
