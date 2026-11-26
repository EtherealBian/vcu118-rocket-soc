// Exercise the generated *coupler buffer module*, not a behavioral FIFO substitute.
#include "VTLBuffer_a12d64s8k1z2u.h"
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <stdexcept>

using DUT = VTLBuffer_a12d64s8k1z2u;
struct Packet { uint64_t data; unsigned opcode, size, source, address, mask; };
struct Channel {
    std::deque<Packet> queue;
    Packet pending{};
    bool valid = false;
    unsigned pushes=0, pops=0, stalled=0, simultaneous=0, full=0, dropped=0;
};
static uint64_t rng=UINT64_C(0x45d9f36ab7140521);
static uint64_t randomWord() { rng ^= rng << 13; rng ^= rng >> 7; return rng ^= rng << 17; }
static unsigned cycle;
static void check(bool good, const char* message) {
    if (!good) throw std::runtime_error("cycle="+std::to_string(cycle)+" "+message);
}
static void offer(Channel& c, bool newOffer) {
    if (!c.valid && newOffer) {
        auto b=randomWord(); c.pending={randomWord(),unsigned(b&7),unsigned(b>>3&3),unsigned(b>>5&255),unsigned(b>>13&4095),unsigned(b>>25&255)};
        c.valid=true;
    }
}
static void step(Channel& c, bool inReady, bool outValid, bool outReady, Packet actual, bool isA, bool reset) {
    // A synchronous reset at this edge discards the old occupancy. No traffic
    // is credited on that edge; the next cycle must exhibit an empty queue.
    if (reset) { c.dropped += c.queue.size(); c.queue.clear(); c.valid=false; return; }
    check(inReady == (c.queue.size()<2),"input ready differs from registered occupancy");
    check(outValid == !c.queue.empty(),"output valid differs from registered occupancy");
    if (outValid) {
        const auto& p=c.queue.front();
        check(p.data==actual.data && p.opcode==actual.opcode && p.size==actual.size && p.source==actual.source && (!isA || (p.address==actual.address && p.mask==actual.mask)),"payload/order changed, including stalled head");
    }
    bool push=c.valid && inReady, pop=outValid && outReady;
    c.full += c.queue.size()==2; c.stalled += outValid && !outReady; c.simultaneous += push&&pop;
    if(pop){++c.pops; c.queue.pop_front();}
    if(push){++c.pushes; c.queue.push_back(c.pending); c.valid=false;}
}
int main() {
    try {
        DUT d; Channel a,b;
        for(cycle=0;cycle<4112;++cycle) {
            bool reset=cycle==0 || cycle==18 || cycle==2048;
            bool drain=cycle>=4096;
            // Both queues are deliberately held full before each mid-run reset.
            bool fill=(cycle>=1 && cycle<=18) || (cycle>=2032 && cycle<=2048);
            offer(a,!drain && (fill || (randomWord()&3))); offer(b,!drain && (fill || (randomWord()&3)));
            d.clock=0; d.reset=reset; d.auto_in_a_valid=a.valid; d.auto_out_d_valid=b.valid;
            d.auto_out_a_ready=drain || (!fill && (randomWord()&3)); d.auto_in_d_ready=drain || (!fill && (randomWord()&1));
            const auto &p=a.pending,&q=b.pending;
            d.auto_in_a_bits_opcode=p.opcode; d.auto_in_a_bits_param=0; d.auto_in_a_bits_size=p.size; d.auto_in_a_bits_source=p.source;
            d.auto_in_a_bits_address=p.address; d.auto_in_a_bits_mask=p.mask; d.auto_in_a_bits_data=p.data; d.auto_in_a_bits_corrupt=0;
            d.auto_out_d_bits_opcode=q.opcode; d.auto_out_d_bits_size=q.size; d.auto_out_d_bits_source=q.source; d.auto_out_d_bits_data=q.data;
            d.eval();
            if (!reset && d.auto_in_d_valid) check(!(d.auto_in_d_bits_param || d.auto_in_d_bits_sink || d.auto_in_d_bits_denied || d.auto_in_d_bits_corrupt),"D constant fields changed");
            step(a,d.auto_in_a_ready,d.auto_out_a_valid,d.auto_out_a_ready,{d.auto_out_a_bits_data,d.auto_out_a_bits_opcode,d.auto_out_a_bits_size,d.auto_out_a_bits_source,d.auto_out_a_bits_address,d.auto_out_a_bits_mask},true,reset);
            step(b,d.auto_out_d_ready,d.auto_in_d_valid,d.auto_in_d_ready,{d.auto_in_d_bits_data,d.auto_in_d_bits_opcode,d.auto_in_d_bits_size,d.auto_in_d_bits_source,0,0},false,reset);
            d.clock=1; d.eval();
        }
        d.final();
        for(const auto* c:{&a,&b}){
            check(c->queue.empty() && !c->valid && c->pushes==c->pops+c->dropped && c->dropped==4 && c->simultaneous>200 && c->full>200 && c->stalled>200,"insufficient coverage or incomplete drain");
            std::cout<<(c==&a?'A':'D')<<" push="<<c->pushes<<" pop="<<c->pops<<" simultaneous="<<c->simultaneous<<" full="<<c->full<<" stalled="<<c->stalled<<" reset_discard="<<c->dropped<<'\n';
        }
        std::cout<<"GENERATED_AD_BUFFER_STALL_RESET_PASS cycles="<<cycle<<'\n'; return EXIT_SUCCESS;
    } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return EXIT_FAILURE;}
}
