// Read the same pre-edge as LoadUse. No forced state or changes to the RTL.
#define AC_TILE(k) (r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__##k)
struct AddressChain : LoadUse {
  std::ofstream addr;
  explicit AddressChain(const std::string &prefix) : LoadUse(prefix), addr(prefix+".addr") {
    need(addr.good(),"cannot open address capture");
  }
  template<class Root> void before(const Root &r,const QData *const *ftq,uint64_t cycle,bool user) {
    LoadUse::before(r,ftq,cycle,user);
    if (!user) return;
    auto selected=[&](unsigned slot) {auto pc=pc_for(slot); return pc==0x13ea2 || pc==0x13eac;};
    auto request=[&](unsigned lane,unsigned slot,unsigned pdst,unsigned ldq,uint64_t base,uint64_t ea,bool ld) {
      if (!selected(slot)) return;
      need(ld,"address request is not a load");
      addr<<"A "<<cycle<<' '<<ticket[slot]<<' '<<lane<<' '<<pdst<<' '<<ldq<<' '<<base<<' '<<ea<<'\n';
    };
#define AREQ(n) if(AC_TILE(_core_io_lsu_exe_##n##_req_valid)) request(n,C(iregister_read__DOT__exe_reg_uops_##n##_rob_idx),C(iregister_read__DOT__exe_reg_uops_##n##_pdst),C(iregister_read__DOT__exe_reg_uops_##n##_ldq_idx),C(iregister_read__DOT__exe_reg_rs1_data_##n),AC_TILE(_core_io_lsu_exe_##n##_req_bits_addr),C(iregister_read__DOT__exe_reg_uops_##n##_uses_ldq))
    AREQ(0); AREQ(1);
#undef AREQ
    auto result=[&](unsigned lane,unsigned slot,unsigned pdst,uint64_t value,bool cache,bool dvalid,bool dload,unsigned dq,uint64_t dval,bool fvalid,unsigned fq) {
      if (!selected(slot)) return;
      // The LSU chooses a cache response over a possible simultaneous STQ candidate.
      need(cache ? dvalid && dload && value==dval : fvalid,"invalid selected load response source");
      addr<<(cache?"C ":"F ")<<cycle<<' '<<ticket[slot]<<' '<<lane<<' '<<pdst<<' '<<(cache?dq:fq)<<' '<<value<<'\n';
    };
#define SOURCE(n,sel) AC_TILE(lsu__DOT__##sel),AC_TILE(_dcache_io_lsu_resp_##n##_valid),AC_TILE(_dcache_io_lsu_resp_##n##_bits_uop_uses_ldq),AC_TILE(_dcache_io_lsu_resp_##n##_bits_uop_ldq_idx),AC_TILE(_dcache_io_lsu_resp_##n##_bits_data),AC_TILE(lsu__DOT__wb_forward_valid_##n),AC_TILE(lsu__DOT__wb_forward_ldq_idx_##n)
    if(C(_memExeUnit_io_ll_iresp_valid)) result(0,C(_ll_wbarb_io_out_bits_uop_rob_idx),C(_ll_wbarb_io_out_bits_uop_pdst),C(_ll_wbarb_io_out_bits_data),SOURCE(0,_GEN_1773));
    if(C(_memExeUnit_1_io_ll_iresp_valid)) result(1,C(_memExeUnit_1_io_ll_iresp_bits_uop_rob_idx),C(_memExeUnit_1_io_ll_iresp_bits_uop_pdst),AC_TILE(_lsu_io_core_exe_1_iresp_bits_data),SOURCE(1,_GEN_1824));
#undef SOURCE
  }
  void finish(){ LoadUse::finish(); addr.close(); need(bool(addr),"incomplete address capture"); }
};
#undef AC_TILE
