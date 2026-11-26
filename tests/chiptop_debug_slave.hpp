// Exercise the debug *slave*, rather than only the DMI system-bus master.
// The halted hart runs one load/store in progbuf. One observer is the hart
// through CBUS; the other is the external DMI DATA0..DATA7 interface.
static void exerciseDebugSlave(DebugPort& d) {
 d.syncAbstract();
 const auto info=d.rd(0x12), cs=d.rd(0x16); const unsigned addr=info&0xfff;
 std::cerr<<"DEBUG_SLAVE_CAPS hartinfo=0x"<<std::hex<<info<<" abstractcs=0x"<<cs<<std::dec<<"\n";
 need((info&(1u<<16)) && ((info>>12)&15)==8 && addr==0x380 && (cs&15)==8 && ((cs>>24)&31)>=2,"unexpected debug slave capabilities");
 std::array<uint32_t,8> saved{};for(unsigned i=0;i<8;++i)saved[i]=d.rd(4+i);
 const auto p0=d.rd(0x20),p1=d.rd(0x21); const auto x7=d.readGpr(7);
 auto setData=[&](unsigned g,uint64_t v){d.wr(4+2*g,uint32_t(v));d.wr(5+2*g,uint32_t(v>>32));};
 auto data=[&](unsigned g){const uint64_t lo=d.rd(4+2*g),hi=d.rd(5+2*g);return (hi<<32)|lo;};
 auto execute=[&](uint32_t instruction){d.wr(0x20,instruction);d.wr(0x21,0x00100073);d.wr(0x17,1u<<18);d.syncAbstract();};
 unsigned stores=0,loads=0;
 for(uint64_t pattern:{UINT64_C(0xf1a28374c596b7e8),UINT64_C(0x102f3e4d5c6b7a89),UINT64_C(0xa55a33cc69f00f96)}) {
  for(unsigned size=0;size!=4;++size){const unsigned bytes=1u<<size;
   const uint64_t low=bytes==8?~UINT64_C(0):(UINT64_C(1)<<(8*bytes))-1;
   for(unsigned g=0;g<4;++g)for(unsigned lane=0;lane<8;lane+=bytes){const unsigned off=addr+8*g+lane; const uint64_t mask=low<<(8*lane);
    const uint64_t src=pattern ^ (UINT64_C(0x0101010101010101)*lane), old=~pattern;
    std::array<uint64_t,4> golden{};d.writeReg(0x1007,src);
    for(unsigned i=0;i<4;++i){golden[i]=old^(UINT64_C(0x36d97b5184acf20e)*i);setData(i,golden[i]);}
    // S-type: s[b/h/w/d] x7,off(x0). Check every byte including untouched lanes.
    execute(((off>>5)<<25)|(7u<<20)|(size<<12)|((off&31)<<7)|0x23);
    golden[g]=(golden[g]&~mask)|((src&low)<<(8*lane));
    for(unsigned i=0;i<4;++i)need(data(i)==golden[i],"debug slave store adjacent-bank/byte-enable/data mismatch");++stores;
    // I-type: lb[u]/lh[u]/lw[u]/ld x7,off(x0). Read GPR only after execution:
    // abstract GPR read itself borrows DATA0/1, so re-seed every case.
    setData(g,pattern);execute((off<<20)|((size==3?3u:4u+size)<<12)|(7u<<7)|0x03);
    need(d.readGpr(7)==((pattern>>(8*lane))&low),"debug slave load lane/extension mismatch");++loads;
   }
  }
 }
 d.writeReg(0x1007,x7);need(d.readGpr(7)==x7,"failed to restore x7");d.wr(0x20,p0);d.wr(0x21,p1);for(unsigned i=0;i<8;++i)d.wr(4+i,saved[i]);
 need(stores==180 && loads==180,"debug lane matrix incomplete");
 std::cout<<"\nDEBUG_SLAVE_LANES_CHECKED stores="<<stores<<" loads="<<loads<<" bank_bytes=32 transfer_bytes=1,2,4,8 data_address=0x"<<std::hex<<addr<<std::dec<<"\n";
}
