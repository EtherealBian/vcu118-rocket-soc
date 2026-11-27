// Retired instructions are joined by dispatch ticket. A held lane keeps its
// original decode edge, even if the adjacent lane has already dispatched.
#include <unordered_map>
#define CD_TILE(k) (r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__##k)
struct CopyDecode : Redirects {
  struct Packet { uint64_t tick=0; unsigned inst=0, ftq=0, uopc=0; } lane[4];
  std::unordered_map<uint32_t,unsigned> want;
  const QData *const *pcs=nullptr;
  std::ofstream out;
  explicit CopyDecode(const std::string &prefix): Redirects(prefix), out(prefix+".decode") {
    std::ifstream f(prefix+".select"); uint32_t key; unsigned pc;
    while(f>>key>>pc) need((pc==0x13b62||pc==0x13b64)&&want.emplace(key,pc).second,"bad decode selection");
    need(f.eof()&&!want.empty()&&bool(out),"missing decode inputs");
  }
  template<class Root> void before(const Root &r,const QData *const *ftq,uint64_t cycle,bool user) {
    Redirects::before(r,ftq,cycle,user); pcs=ftq;
  }
  template<class Root> void dispatch(const Root &r,uint64_t cycle) {
    Redirects::dispatch(r,cycle); const unsigned row=C(rob__DOT__rob_tail);
    const bool fire[]={bool(C(dec_fire_0)),bool(C(dec_fire_1)),bool(C(dec_fire_2)),bool(CD_TILE(_core_io_ifu_fetchpacket_ready))};
    const bool kill=CD_TILE(_core_io_ifu_redirect_flush), ready=!C(dis_stalls_3);
#define CD_DEC(n,f) C(_decode_units_##n##_io_deq_uop_##f)
#define CD_REG(p,f) C(rename_stage__DOT__r_uop_##p##f)
#define CD_LANE(n,p,v) { \
    auto &old=lane[n]; unsigned slot=4*row+n; bool sent=(ticket[slot]>>7)==cycle; \
    need(bool(old.tick)==bool(C(rename_stage__DOT__##v)),"shadow decode valid differs from real rename"); \
    if(sent) { \
      need(old.tick && old.tick<cycle && old.ftq==CD_REG(p,ftq_idx) && old.uopc==CD_REG(p,uopc),"held decode identity mismatch"); \
      auto it=want.find(ticket[slot]); if(it!=want.end()) { \
        need(old.ftq<40 && pcs && ((*pcs[old.ftq]&~UINT64_C(63))+CD_REG(p,pc_lob)-2*CD_REG(p,edge_inst))==it->second,"wrong dispatch PC"); \
        out<<ticket[slot]<<' '<<old.tick<<' '<<old.inst<<' '<<unsigned(CD_REG(p,is_rvc))<<' '<<unsigned(CD_REG(p,exception)) \
           <<' '<<unsigned(CD_REG(p,is_sfb))<<' '<<unsigned(CD_REG(p,fp_val))<<' '<<unsigned(CD_REG(p,ldst_val)) \
           <<' '<<unsigned(CD_REG(p,dst_rtype))<<' '<<unsigned(CD_REG(p,lrs1_rtype))<<' '<<unsigned(CD_REG(p,lrs2_rtype)) \
           <<' '<<unsigned(CD_REG(p,ldst))<<' '<<unsigned(CD_REG(p,lrs1))<<' '<<unsigned(CD_REG(p,lrs2)) \
           <<' '<<unsigned(CD_REG(p,uses_ldq))<<' '<<unsigned(CD_REG(p,uses_stq))<<' '<<unsigned(CD_REG(p,is_amo)) \
           <<' '<<unsigned(CD_REG(p,mem_cmd))<<'\n'; want.erase(it); \
      } \
    } \
    if(kill||ready||sent) old={}; \
    if(fire[n]) {need(!kill&&ready,"decode fired without rename acceptance"); old={cycle,CD_DEC(n,inst),CD_DEC(n,ftq_idx),CD_DEC(n,uopc)};} \
  }
    CD_LANE(0,,r_valid);CD_LANE(1,1_,r_valid_1);CD_LANE(2,2_,r_valid_2);CD_LANE(3,3_,r_valid_3);
#undef CD_LANE
#undef CD_REG
#undef CD_DEC
  }
  void finish(){need(want.empty(),"retired decode missing");out.close();need(bool(out),"decode write failed");Redirects::finish();}
};
#undef CD_TILE
