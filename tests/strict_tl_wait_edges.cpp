// Drive the actual testbench responder directly. The model is instantiated for the pin
// interface only: no eval(), hart execution, or physical hardware is involved.
#define main old_main
#include "rocket_chiptop.cpp"
#undef main
#include "strict_tl_wait.hpp"

int main(int argc,char **argv) {
  try {
    need(argc == 3, "expected output log and delay");
    const unsigned delay = std::stoul(argv[2]);
    StrictWaitRam m(argv[1],delay); VChipTop t;
    uint64_t tick=1; const uint32_t addr=0x80020000;
    auto word=[](unsigned i){return UINT64_C(0x55aacc0011223300)+i;};
    auto step=[&](bool u, bool aready, bool dv, unsigned op, unsigned src, uint64_t data) {
      m.drive(t);
      need(t.tl_slave_0_a_ready==aready && t.tl_slave_0_d_valid==dv,"wrong A ready/D valid on fixture edge");
      if(dv) need(t.tl_slave_0_d_bits_opcode==op && t.tl_slave_0_d_bits_size==6 &&
                  t.tl_slave_0_d_bits_source==src && t.tl_slave_0_d_bits_data==data,"wrong held D response");
      m.observe(t,u,tick++);
    };
    t.tl_slave_0_a_valid=1; t.tl_slave_0_a_bits_opcode=0; t.tl_slave_0_a_bits_source=5;
    t.tl_slave_0_a_bits_address=addr; t.tl_slave_0_a_bits_size=6; t.tl_slave_0_a_bits_mask=255;
    t.tl_slave_0_a_bits_corrupt=0; t.tl_slave_0_d_ready=1;
    for(unsigned i=0;i<8;i++) {t.tl_slave_0_a_bits_data=word(i); step(true,true,false,0,0,0);}
    // Offer the next valid Get while the Put's ack is backpressured. It must not be accepted yet.
    t.tl_slave_0_a_bits_opcode=4; t.tl_slave_0_a_bits_source=6; t.tl_slave_0_d_ready=0;
    step(true,false,true,0,5,0); step(true,false,true,0,5,0);
    t.tl_slave_0_d_ready=1; step(true,false,true,0,5,0);
    for(unsigned j=0;j<2;j++) {
      // A Get accepted in U is charged even if privilege changes while it is pending.
      // A Get accepted out of U is not charged even if U becomes active on the next edge.
      bool user=j==0; const unsigned src=6+j;
      t.tl_slave_0_a_valid=1; t.tl_slave_0_a_bits_source=src; step(user,true,false,0,0,0);
      t.tl_slave_0_a_bits_source=7; // next A remains valid and stable throughout the response
      for(unsigned i=0;i<(user?delay:0);i++) step(!user,false,false,0,0,0);
      for(unsigned i=0;i<8;i++) {
        t.tl_slave_0_d_ready=0; step(!user,false,true,1,src,word(i));
        t.tl_slave_0_d_ready=1; step(!user,false,true,1,src,word(i));
      }
    }
    t.tl_slave_0_a_valid=0; step(false,true,false,0,0,0);
    need(m.reads==2 && m.writes==1 && !m.dvalid && !m.pendingPut && !m.live,"bad final responder state");
    m.finish(tick); std::cout<<"WAIT_PIN_FIXTURE_OK delay="<<delay<<"\n"; return 0;
  } catch(const std::exception &e){std::cerr<<e.what()<<'\n'; return 1;}
}
