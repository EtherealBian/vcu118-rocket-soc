// On the sealed model, distinguish arriving at the AGU from an accepted cache
// request. Tag the latter using the live LDQ entry, not just a circular index.
#define XL(k) (r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__##k)
struct LeftLoad : AddressChain {
  std::ofstream path;
  unsigned prev_fire=0;
  explicit LeftLoad(const std::string &prefix): AddressChain(prefix),path(prefix+".left") {need(path.good(),"open left trace");}
  template<class Root> void before(const Root &r,const QData *const *ftq,uint64_t cycle,bool user) {
    AddressChain::before(r,ftq,cycle,user);
    unsigned fire=XL(dcache__DOT___s1_valid_T_19)?(XL(_lsu_io_dmem_req_bits_0_valid)+2*XL(_lsu_io_dmem_req_bits_1_valid)):0;
    const unsigned prev=prev_fire; prev_fire=fire;
    if (!user) return;
    auto selected=[&](unsigned s){auto p=pc_for(s);return p==0x13ea4 || p==0x13e9e;};
    auto put=[&](char kind,unsigned lane,unsigned slot,unsigned q,unsigned d,uint64_t v,uint64_t x){
      path<<kind<<' '<<cycle<<' '<<ticket[slot]<<' '<<lane<<' '<<q<<' '<<d<<' '<<v<<' '<<x<<'\n';
    };
    auto agu=[&](unsigned l,unsigned s,unsigned q,unsigned d,uint64_t base,uint64_t ea,bool ld){
      if(selected(s)){need(ld,"not load at AGU"); put('A',l,s,q,d,base,ea);}
    };
#define AG(n) if(XL(_core_io_lsu_exe_##n##_req_valid)) agu(n,C(iregister_read__DOT__exe_reg_uops_##n##_rob_idx),C(iregister_read__DOT__exe_reg_uops_##n##_ldq_idx),C(iregister_read__DOT__exe_reg_uops_##n##_pdst),C(iregister_read__DOT__exe_reg_rs1_data_##n),XL(_core_io_lsu_exe_##n##_req_bits_addr),C(iregister_read__DOT__exe_reg_uops_##n##_uses_ldq))
    AG(0); AG(1);
#undef AG
    auto stage=[&](bool s2,unsigned l,unsigned q,uint64_t pa,bool hit,bool nack){
      unsigned s,d; bool valid;
#define LQ(i) case i: s=XL(lsu__DOT__ldq_##i##_bits_uop_rob_idx); d=XL(lsu__DOT__ldq_##i##_bits_uop_pdst); valid=XL(lsu__DOT__ldq_##i##_valid); break;
      switch(q){LQ(0)LQ(1)LQ(2)LQ(3)LQ(4)LQ(5)LQ(6)LQ(7)LQ(8)LQ(9)LQ(10)LQ(11)LQ(12)LQ(13)LQ(14)LQ(15)LQ(16)LQ(17)LQ(18)LQ(19)LQ(20)LQ(21)LQ(22)LQ(23)LQ(24)LQ(25)LQ(26)LQ(27)LQ(28)LQ(29)LQ(30)LQ(31)default:throw std::runtime_error("invalid LDQ index");}
#undef LQ
      if(!valid || !selected(s)) return;
      if(!s2) need(prev & (1u<<l),"LSU S1 without previous lane handshake");
      put(s2?'T':'S',l,s,q,d,pa,s2?(unsigned(hit)+2*unsigned(nack)):0);
    };
#define DC(k) XL(dcache__DOT__##k)
#define ST(n,v1,v2) if(DC(s1_type)==4 && DC(v1) && DC(s1_req_##n##_uop_uses_ldq)) stage(false,n,DC(s1_req_##n##_uop_ldq_idx),DC(s1_req_##n##_addr),false,false); if(DC(s2_type)==4 && DC(v2) && DC(s2_req_##n##_uop_uses_ldq)) stage(true,n,DC(s2_req_##n##_uop_ldq_idx),DC(s2_req_##n##_addr),DC(s2_hit_##n),XL(_dcache_io_lsu_nack_##n##_valid));
    ST(0,s1_valid_REG,s2_valid_REG); ST(1,s1_valid_REG_1,s2_valid_REG_1);
#undef ST
#undef DC
    auto result=[&](unsigned l,unsigned s,unsigned d,uint64_t val,bool cache,bool dv,bool dl,unsigned dq,uint64_t data,bool fv,unsigned fq,unsigned sq){
      if(!selected(s))return;
      need(cache?(dv && dl && data==val):fv,"result source mismatch");
      put(cache?'C':'F',l,s,cache?dq:fq,d,val,cache?0:sq);
    };
#define RES(n,sel) XL(lsu__DOT__##sel),XL(_dcache_io_lsu_resp_##n##_valid),XL(_dcache_io_lsu_resp_##n##_bits_uop_uses_ldq),XL(_dcache_io_lsu_resp_##n##_bits_uop_ldq_idx),XL(_dcache_io_lsu_resp_##n##_bits_data),XL(lsu__DOT__wb_forward_valid_##n),XL(lsu__DOT__wb_forward_ldq_idx_##n),XL(lsu__DOT__wb_forward_stq_idx_##n)
    if(C(_memExeUnit_io_ll_iresp_valid)) result(0,C(_ll_wbarb_io_out_bits_uop_rob_idx),C(_ll_wbarb_io_out_bits_uop_pdst),C(_ll_wbarb_io_out_bits_data),RES(0,_GEN_1773));
    if(C(_memExeUnit_1_io_ll_iresp_valid)) result(1,C(_memExeUnit_1_io_ll_iresp_bits_uop_rob_idx),C(_memExeUnit_1_io_ll_iresp_bits_uop_pdst),XL(_lsu_io_core_exe_1_iresp_bits_data),RES(1,_GEN_1824));
#undef RES
  }
  void finish(){AddressChain::finish();path.close();need(bool(path),"incomplete left trace");}
};
#undef XL
