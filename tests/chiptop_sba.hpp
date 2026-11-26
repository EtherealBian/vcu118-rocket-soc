// Model-side USB/JTAG replacement: every memory access below is a public DMI
// register transaction on the simulated TAP. The scratch range is guest RAM.
struct SbaMailbox {
 static constexpr unsigned cs=0x38, addr=0x39, data=0x3c;
 static constexpr uint32_t w32=2u<<17, onAddr=1u<<20, box=0x81000000u, entry=0x80000000u;
 uint32_t expected=0x7f4a7c15u;
 uint32_t wait(DebugPort& d, unsigned error=0) {
  uint32_t status=0; for(unsigned n=0;n<32;++n){status=d.rd(cs);if(!(status&(1u<<21)))break;}
  need(!(status&((1u<<21)|(1u<<22)))&&((status>>12)&7)==error,"unexpected SBA busy/error");return status;
 }
 void write(DebugPort& d,uint32_t a,uint32_t v) {d.wr(cs,w32);d.wr(addr,a);d.wr(data,v);wait(d);}
 uint32_t read(DebugPort& d,uint32_t a){d.wr(cs,w32|onAddr);d.wr(addr,a);wait(d);return d.rd(data);}
 void upload(DebugPort& d,const char* path){
  d.connectHalt();auto caps=wait(d);need((caps>>29)==1 && ((caps>>5)&127)>=32 && (caps&4),"missing 32-bit SBA capability");
  std::ifstream stream(path,std::ios::binary|std::ios::ate);need(bool(stream),"missing guest");auto n=stream.tellg();need(n>0 && n<=4096,"invalid guest length");stream.seekg(0);
  std::vector<uint8_t> bytes((size_t(n)+3)&~size_t(3),0);stream.read(reinterpret_cast<char*>(bytes.data()),n);need(bool(stream),"short guest");
  for(unsigned i=0;i<bytes.size();i+=4){uint32_t v=0;for(unsigned j=0;j<4;j++)v|=uint32_t(bytes[i+j])<<(8*j);write(d,entry+i,v);need(read(d,entry+i)==v,"SBA program readback");}
  uint32_t x=0x624acbe5;for(unsigned i=0;i<32;i++){x^=x<<13;x^=x>>17;x^=x<<5;write(d,box+4*i,x);need(read(d,box+4*i)==x,"SBA mailbox readback");expected=(expected<<5)|(expected>>27);expected+=x^(0x9e3779b9u+i);}
  write(d,box+256,~expected);d.wr(cs,w32|onAddr);d.wr(addr,box+1);wait(d,3); // unaligned read must fail
  d.wr(cs,w32|(7u<<12));wait(d);need(read(d,box+256)==~expected,"SBA W1C recovery");
  // Boot sets entry through abstract registers/progbuf only; it does not write memory.
  d.boot(entry,0,true);std::cerr<<"SBA_UPLOAD bytes="<<n<<" mailbox_words=32 misaligned_read=3 recovered=1\n";
 }
 void verify(DebugPort& d){d.connectHalt();auto actual=read(d,box+256);need(actual==expected,"SBA guest response mismatch");std::cerr<<"SBA_GUEST_READBACK expected=0x"<<std::hex<<expected<<" actual=0x"<<actual<<std::dec<<"\n";}
};
