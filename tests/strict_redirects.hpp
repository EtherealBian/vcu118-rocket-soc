// Instrument an unmodified stock model. The dispatch edge plus ROB index is
// a dynamic instruction ID: a circular slot or a static PC alone is ambiguous.
#define TILE(field) (r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__##field)
struct Redirects {
  std::ofstream commits, redirects;
  uint32_t ticket[128]{};
  bool expect_s1 = false;
  uint64_t s1_pc = 0;
  explicit Redirects(const std::string &prefix)
      : commits(prefix+".tickets",std::ios::binary), redirects(prefix+".redirects") {
    need(bool(commits)&&bool(redirects),"open redirect traces");
  }
  template<class Root> void before(const Root &r,const QData *const *ftq,uint64_t cycle,bool user) {
    // Pre-edge S0 selected on a backend redirect must really reach next S1.
    if (expect_s1) need(TILE(frontend__DOT__s1_valid)&&TILE(frontend__DOT__s1_vpc)==s1_pc,"redirect target did not reach S1");
    expect_s1=false;
    if (!user || !C(b2_mispredict)) return;
    need(!C(REG)&&!C(REG_1)&&TILE(_core_io_ifu_redirect_flush)&&TILE(_core_io_ifu_redirect_val)
         &&TILE(frontend__DOT__s0_valid),"B2 not unique source of frontend redirect");
    auto fi=C(b2_uop_ftq_idx), slot=C(b2_uop_rob_idx); need(fi<40&&slot<128&&ticket[slot],"B2 identity unavailable");
    uint64_t pc=((*ftq[fi]&~UINT64_C(63))+C(b2_uop_pc_lob))-2*C(b2_uop_edge_inst);
    expect_s1=true; s1_pc=TILE(frontend__DOT__s0_vpc);
    redirects<<cycle<<' '<<ticket[slot]<<' '<<pc<<' '<<s1_pc<<' '<<unsigned(C(b2_cfi_type))<<' '
             <<unsigned(C(b2_taken))<<' '<<(C(b2_uop_is_rvc)?2:4)<<'\n';
  }
  void commit(uint64_t cycle,unsigned slot) {
    need(slot<128&&ticket[slot]&&(ticket[slot]>>7)<cycle,"committed ROB slot lacks older allocation");
    for (uint32_t w:{uint32_t(cycle),ticket[slot]})
      for (unsigned j=0;j<4;++j) commits.put(char(w>>(8*j)));
  }
  template<class Root> void dispatch(const Root &r,uint64_t cycle) {
    const bool valid[]={bool(TILE(_core_io_lsu_dis_uops_0_valid)),bool(TILE(_core_io_lsu_dis_uops_1_valid)),
                        bool(TILE(_core_io_lsu_dis_uops_2_valid)),bool(TILE(_core_io_lsu_dis_uops_3_valid))};
    const unsigned row=C(rob__DOT__rob_tail); need(row<32&&cycle<(1u<<25),"dispatch ticket overflow");
    for(unsigned lane=0;lane<4;++lane) if(valid[lane]) {
      unsigned slot=4*row+lane; ticket[slot]=(uint32_t(cycle)<<7)|slot;
    }
  }
  void finish(){commits.close();redirects.close();need(bool(commits)&&bool(redirects)&&!expect_s1,"unfinished redirect traces");}
};
#undef TILE
