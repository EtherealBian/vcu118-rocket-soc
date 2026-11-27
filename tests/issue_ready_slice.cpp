#include "Vissue_ready_miter.h"
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <random>
#include <algorithm>
#include <array>
int main() {
    Vissue_ready_miter dut; uint64_t cycle=0; unsigned prev=0, prev2=0;
    auto sample=[&](uint64_t x) {
        x &= (uint64_t(1)<<40)-1; dut.clk=0;dut.available=x;dut.eval();dut.clk=1;dut.eval();
        unsigned cnt=__builtin_popcountll(x); unsigned cur=(1u<<std::min(cnt,4u))-1;
        if(cycle>=2 && (dut.stock_ready!=prev2 || dut.candidate_ready!=prev2)) throw std::runtime_error("registered credit/latency mismatch");
        prev2=prev;prev=cur;++cycle;
    };
    // Exact positions for every mask up to three bits, where a single error changes a lane.
    sample(0);for(unsigned i=0;i<40;++i){sample(1ull<<i);for(unsigned j=0;j<i;++j){sample((1ull<<i)|(1ull<<j));for(unsigned k=0;k<j;++k)sample((1ull<<i)|(1ull<<j)|(1ull<<k));}}
    std::mt19937_64 rng(0x9e3765);std::array<unsigned,40> pos; for(unsigned i=0;i<40;++i)pos[i]=i;
    for(unsigned i=0;i<100000;++i){std::shuffle(pos.begin(),pos.end(),rng);unsigned weight=i%41; uint64_t x=0;for(unsigned j=0;j<weight;++j)x|=1ull<<pos[j];sample(x);sample(0);}
    sample(0);sample(0);dut.final();std::printf("ISSUE_SLICE_CYCLE_CHECK_PASS cycles=%llu checked=%llu positions=40 weights=0..40 lanes=4\n",(unsigned long long)cycle,(unsigned long long)(cycle-2));
}
