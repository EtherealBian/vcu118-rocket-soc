// All signals are sampled before the same rising edge. Follow only previously
// identified retired tickets, never just a PC, LDQ entry or recyclable ROB slot.
#include <unordered_map>
#define RV_TILE(k) (r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__##k)
#define RV_BUSY(p,n,s) &C(rob__DOT__rob_bsy_##p##n)
struct Reversal : Redirects {
  static constexpr unsigned move_pc=0x13b62, load_pc=0x13b64, branch_pc=0x13b6a;
  std::unordered_map<uint32_t,unsigned> selected;
  std::vector<uint32_t> pending;
  std::ofstream trace;
  explicit Reversal(const std::string &prefix): Redirects(prefix), trace(prefix+".reversal") {
    std::ifstream f(prefix+".select"); uint32_t k; unsigned pc;
    while(f>>k>>pc) need((pc==move_pc || pc==load_pc || pc==branch_pc) && selected.emplace(k,pc).second,"invalid reversal selection");
    need(f.eof() && !selected.empty() && bool(trace),"open reversal inputs");
  }
  unsigned pc_at(unsigned slot) const {
    auto i=selected.find(ticket[slot]); return i==selected.end()?0:i->second;
  }
  template<class Root> void dispatch(const Root &r,uint64_t cycle) {
    Redirects::dispatch(r,cycle);
    unsigned row=C(rob__DOT__rob_tail);
    for(unsigned lane=0;lane<4;++lane) {
      unsigned slot=4*row+lane;
      if(ticket[slot]>>7==cycle && pc_at(slot)==branch_pc) pending.push_back(ticket[slot]);
    }
  }
  template<class Root> void before(const Root &r,const QData *const *ftq,uint64_t cycle,bool user) {
    Redirects::before(r,ftq,cycle,user);
    if(!user) return;
    const CData *const busy[4][32]={{RANGE32(RV_BUSY,,0)},{RANGE32(RV_BUSY,1_,0)},
                                    {RANGE32(RV_BUSY,2_,0)},{RANGE32(RV_BUSY,3_,0)}};
    auto put=[&](char kind,unsigned s,unsigned lane,uint64_t a,uint64_t b) {
      trace<<kind<<' '<<cycle<<' '<<ticket[s]<<' '<<lane<<' '<<a<<' '<<b<<'\n';
    };
    for(auto i=pending.begin();i!=pending.end();) {
      unsigned slot=*i&127; need(ticket[slot]==*i,"branch slot recycled before clearing");
      if(*busy[slot%4][slot/4]) {++i;continue;}
      need((*i>>7)+1<cycle,"new branch was never busy"); put('W',slot,slot%4,0,0); i=pending.erase(i);
    }
    auto address=[&](unsigned n,unsigned s,uint64_t base,uint64_t ea,bool ld) {
      if(pc_at(s)==load_pc) {need(ld,"not a load request");put('A',s,n,base,ea);}
    };
#define RV_AG(n) if(RV_TILE(_core_io_lsu_exe_##n##_req_valid)) address(n,C(iregister_read__DOT__exe_reg_uops_##n##_rob_idx),C(iregister_read__DOT__exe_reg_rs1_data_##n),RV_TILE(_core_io_lsu_exe_##n##_req_bits_addr),C(iregister_read__DOT__exe_reg_uops_##n##_uses_ldq))
    RV_AG(0); RV_AG(1);
#undef RV_AG
    auto result=[&](unsigned n,unsigned s,uint64_t data,bool cache,bool dv,bool dl,uint64_t cv,bool fv){
      if(pc_at(s)!=load_pc)return;
      need(cache?(dv && dl && cv==data):fv,"invalid load response source");put('L',s,n,data,cache);
    };
#define RV_SRC(n,sel) RV_TILE(lsu__DOT__##sel),RV_TILE(_dcache_io_lsu_resp_##n##_valid),RV_TILE(_dcache_io_lsu_resp_##n##_bits_uop_uses_ldq),RV_TILE(_dcache_io_lsu_resp_##n##_bits_data),RV_TILE(lsu__DOT__wb_forward_valid_##n)
    if(C(_memExeUnit_io_ll_iresp_valid)) result(0,C(_ll_wbarb_io_out_bits_uop_rob_idx),C(_ll_wbarb_io_out_bits_data),RV_SRC(0,_GEN_1773));
    if(C(_memExeUnit_1_io_ll_iresp_valid)) result(1,C(_memExeUnit_1_io_ll_iresp_bits_uop_rob_idx),RV_TILE(_lsu_io_core_exe_1_iresp_bits_data),RV_SRC(1,_GEN_1824));
#undef RV_SRC
    auto alu=[&](unsigned n,unsigned s,uint64_t a,uint64_t b){
      unsigned pc=pc_at(s);if(pc==move_pc || pc==branch_pc)put(pc==move_pc?'M':'E',s,n-2,a,b);
    };
#define RV_ALU(n) if(C(iregister_read__DOT__exe_reg_valids_##n)) alu(n,C(iregister_read__DOT__exe_reg_uops_##n##_rob_idx),C(iregister_read__DOT__exe_reg_rs1_data_##n),C(iregister_read__DOT__exe_reg_rs2_data_##n))
    RV_ALU(2);RV_ALU(3);RV_ALU(4);RV_ALU(5);
#undef RV_ALU
    auto branch=[&](unsigned n,unsigned s,unsigned fi,unsigned lo,bool edge,bool taken,bool miss){
      if(pc_at(s)!=branch_pc)return;
      need(fi<40 && ((*ftq[fi]&~UINT64_C(63))+lo-2*edge)==branch_pc,"wrong B1 branch");put('B',s,n,taken,miss);
    };
#define RV_B(n) if(C(brinfos_##n##_valid)) branch(n,C(brinfos_##n##_uop_rob_idx),C(brinfos_##n##_uop_ftq_idx),C(brinfos_##n##_uop_pc_lob),C(brinfos_##n##_uop_edge_inst),C(brinfos_##n##_taken),C(brinfos_##n##_mispredict))
    RV_B(0);RV_B(1);RV_B(2);RV_B(3);
#undef RV_B
  }
  void finish(){need(pending.empty(),"unresolved reversal branch");trace.close();need(bool(trace),"unfinished reversal capture");Redirects::finish();}
};
#undef RV_BUSY
#undef RV_TILE
