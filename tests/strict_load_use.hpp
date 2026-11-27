// Read-only probes on the original four-wide model. All samples are pre-edge.
#include <unordered_map>
#define LOAD_TILE(k) (r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__##k)
struct LoadUse : Redirects {
  std::unordered_map<uint32_t, unsigned> target;
  std::ofstream flow;
  explicit LoadUse(const std::string &prefix) : Redirects(prefix), flow(prefix+".flow") {
    std::ifstream f(prefix+".select"); uint32_t id; unsigned pc;
    while (f >> id >> pc) need(target.emplace(id,pc).second,"duplicate selected ticket");
    need(f.eof() && !target.empty() && flow.good(),"invalid operand probe inputs");
  }
  unsigned pc_for(unsigned slot) const {
    auto it=target.find(ticket[slot]); return it==target.end()?0:it->second;
  }
  template<class Root> void before(const Root &r,const QData *const *ftq,uint64_t cycle,bool user) {
    Redirects::before(r,ftq,cycle,user);
    if(!user) return;
    auto load=[&](unsigned lane,unsigned slot,unsigned pdst,uint64_t data) {
      auto pc=pc_for(slot);
      if(pc==0x13ea4 || pc==0x13eac) flow<<"L "<<cycle<<' '<<ticket[slot]<<' '<<lane<<' '<<pdst<<' '<<data<<'\n';
    };
    if(C(_memExeUnit_io_ll_iresp_valid))
      load(0,C(_ll_wbarb_io_out_bits_uop_rob_idx),C(_ll_wbarb_io_out_bits_uop_pdst),C(_ll_wbarb_io_out_bits_data));
    if(C(_memExeUnit_1_io_ll_iresp_valid))
      load(1,C(_memExeUnit_1_io_ll_iresp_bits_uop_rob_idx),C(_memExeUnit_1_io_ll_iresp_bits_uop_pdst),LOAD_TILE(_lsu_io_core_exe_1_iresp_bits_data));
    auto exe=[&](unsigned port,unsigned slot,uint64_t a,uint64_t b) {
      if(pc_for(slot)==0x13eda) flow<<"E "<<cycle<<' '<<ticket[slot]<<' '<<(port-2)<<' '<<a<<' '<<b<<'\n';
    };
#define EX(n) if(C(iregister_read__DOT__exe_reg_valids_##n)) exe(n,C(iregister_read__DOT__exe_reg_uops_##n##_rob_idx),C(iregister_read__DOT__exe_reg_rs1_data_##n),C(iregister_read__DOT__exe_reg_rs2_data_##n))
    EX(2); EX(3); EX(4); EX(5);
#undef EX
    auto b1=[&](unsigned lane,unsigned slot,unsigned fi,unsigned lo,unsigned edge,bool taken,bool miss) {
      if(pc_for(slot)!=0x13eda) return;
      need(fi<40,"invalid B1 FTQ index");
      auto pc=((*ftq[fi]&~UINT64_C(63))+lo)-2*edge;
      flow<<"B "<<cycle<<' '<<ticket[slot]<<' '<<lane<<' '<<pc<<' '<<taken<<' '<<miss<<'\n';
    };
#define B1(n) if(C(brinfos_##n##_valid)) b1(n,C(brinfos_##n##_uop_rob_idx),C(brinfos_##n##_uop_ftq_idx),C(brinfos_##n##_uop_pc_lob),C(brinfos_##n##_uop_edge_inst),C(brinfos_##n##_taken),C(brinfos_##n##_mispredict))
    B1(0); B1(1); B1(2); B1(3);
#undef B1
  }
  void finish(){Redirects::finish(); flow.close(); need(bool(flow),"incomplete load-use trace");}
};
#undef LOAD_TILE
