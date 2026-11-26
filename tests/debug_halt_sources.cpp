// SPDX-License-Identifier: MIT
// Test only public ports of the generated debug module. Independent DMI and
// debug clocks. The hart reset *status* and dmactive acknowledge are fixtures;
// this is not a test that an external board reset leaves the debugger alive.
#include "VTLDebugModule.h"
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <fstream>
#include <stdexcept>
#include <string>
static void check(bool ok,const char* msg) { if(!ok)throw std::runtime_error(msg); }
struct Bench {
    VTLDebugModule dm; unsigned ticks=0, half, phase, ntx=0; bool sent=false, got=false; uint32_t result=0; std::ostream& trace; bool sample1=false, sample2=false;
    int guard=-1;
    Bench(unsigned h,unsigned p,std::ostream& out):half(h),phase(p),trace(out) {
        dm.io_dmi_dmiClock=dm.io_debug_clock=dm.io_tl_clock=0;
        dm.io_dmi_dmiReset=dm.io_debug_reset=dm.io_tl_reset=1; dm.io_hartIsInReset_0=0;
        dm.io_ctrl_dmactiveAck=0; dm.io_dmi_dmi_req_valid=0; dm.io_dmi_dmi_req_bits_op=0; dm.io_dmi_dmi_req_bits_addr=0; dm.io_dmi_dmi_req_bits_data=0; dm.io_dmi_dmi_resp_ready=1;
        dm.auto_dmInner_dmInner_tl_in_a_valid=0; dm.auto_dmInner_dmInner_tl_in_a_bits_address=0; dm.auto_dmInner_dmInner_tl_in_a_bits_opcode=0; dm.auto_dmInner_dmInner_tl_in_a_bits_mask=0; dm.auto_dmInner_dmInner_tl_in_a_bits_data=0; dm.auto_dmInner_dmInner_tl_in_a_bits_size=0; dm.auto_dmInner_dmInner_tl_in_a_bits_source=0; dm.auto_dmInner_dmInner_tl_in_d_ready=1;
        dm.auto_dmInner_dmInner_sb2tlOpt_out_a_ready=1; dm.auto_dmInner_dmInner_sb2tlOpt_out_d_valid=0; dm.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_opcode=0; dm.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_param=0; dm.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_size=0; dm.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_sink=0; dm.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_denied=0; dm.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_data=0; dm.auto_dmInner_dmInner_sb2tlOpt_out_d_bits_corrupt=0;
        dm.eval(); run(400); dm.io_dmi_dmiReset=dm.io_debug_reset=dm.io_tl_reset=0; run(500);
    }
    void step() {
        dm.io_ctrl_dmactiveAck=dm.io_ctrl_dmactive; dm.eval();
        bool dc=((ticks+phase)/half)&1, sc=(ticks/3)&1, rise=dc&&!dm.io_dmi_dmiClock;
        bool req=rise&&dm.io_dmi_dmi_req_ready&&dm.io_dmi_dmi_req_valid;
        bool rsp=rise&&dm.io_dmi_dmi_resp_valid&&dm.io_dmi_dmi_resp_ready;
        if(sc && !dm.io_debug_clock) {sample2=sample1; sample1=dm.auto_dmOuter_int_out_sync_0;}
        if(req) {check(!sent,"duplicated DMI request");sent=true;}
        if(rsp) {check(sent&&!got,"stale/duplicate DMI response");check(dm.io_dmi_dmi_resp_bits_resp==0,"DMI error");result=dm.io_dmi_dmi_resp_bits_data;got=true;}
        dm.io_dmi_dmiClock=dc; dm.io_debug_clock=dm.io_tl_clock=sc;dm.eval();++ticks;
        // bit 0 = real pin after this event; bit 1 = two destination edges of
        // delay sampled from that model's public pin before the rising edge.
        // Record DMI handshake events in the same stream to align scenarios.
        trace.put(char(dm.auto_dmOuter_int_out_sync_0 | (sample2<<1) | (req<<2) | (rsp<<3) | (sc<<4) | (dc<<5)));
        if(req) dm.io_dmi_dmi_req_valid=0;
        check(!dm.auto_dmInner_dmInner_sb2tlOpt_out_a_valid,"unexpected SBA");
        if(guard>=0)check(dm.auto_dmOuter_int_out_sync_0==guard,"IRQ changed during hold/overlap");
    }
    void run(unsigned n) {while(n--)step();}
    uint32_t access(unsigned addr,uint32_t data,unsigned op) {
        sent=got=false;dm.io_dmi_dmi_req_bits_addr=addr;dm.io_dmi_dmi_req_bits_data=data;dm.io_dmi_dmi_req_bits_op=op;dm.io_dmi_dmi_req_valid=1;
        for(unsigned i=0;i<8000&&!got;++i)step();check(sent&&got,"DMI timeout");++ntx;return result;
    }
    void ctrl(uint32_t x) {access(0x10,x,2);}
    uint32_t status() {return access(0x11,0,1);}
    void level(bool value) {run(500);check(dm.auto_dmOuter_int_out_sync_0==value,"IRQ did not reach expected value");}
    void test() {
        level(false);ctrl(1);run(500);check(dm.io_ctrl_dmactive,"activation failed");check(status()&(1u<<5),"no halt-on-reset capability");
        ctrl(0x80000001);level(true);ctrl(1);level(false); // ordinary halt alone
        guard=0;dm.io_hartIsInReset_0=1;run(500);dm.io_hartIsInReset_0=0;run(500);guard=-1; // disabled mask
        check((status()&(3u<<18))==(3u<<18),"hart reset history not set");ctrl(0x10000001);run(500);check(!(status()&(3u<<18)),"reset history not cleared");
        ctrl(9);level(false);dm.io_hartIsInReset_0=1;level(true);guard=1;dm.io_hartIsInReset_0=0;run(500); // local request latches without outer halt
        ctrl(0x80000001);run(500);ctrl(0x80000005);run(500); // clear local mask under held outer halt
        guard=-1;ctrl(1);level(false);
        ctrl(9);level(false);ctrl(0x80000001);level(true);guard=1;dm.io_hartIsInReset_0=1;run(500);dm.io_hartIsInReset_0=0;run(500);
        ctrl(1);run(500);guard=-1;ctrl(5);level(false); // drop ordinary halt first; local still asserted
        guard=0;dm.io_hartIsInReset_0=1;run(500);dm.io_hartIsInReset_0=0;run(500);guard=-1;
        ctrl(0);level(false);check(!dm.io_ctrl_dmactive,"deactivation failed"); dm.final();
        std::cout<<"HALT_MERGE_CASE_PASS half="<<half<<" phase="<<phase<<" dmi_transactions="<<ntx<<" ticks="<<ticks<<"\n";
    }
};
int main(int argc,char** argv){try{check(argc==2,"fresh trace file required");std::ofstream bytes(argv[1],std::ios::binary);check(bool(bytes),"open trace failed");for(auto h:{4u,5u,7u})for(auto p:{0u,1u,3u}){Bench b(h,p,bytes);b.test();}bytes.close();check(bool(bytes),"write trace failed");std::cout<<"GENERATED_DEBUG_HALT_SOURCES_PASS clock_cases=9\n";}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
