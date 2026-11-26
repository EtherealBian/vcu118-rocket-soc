// Read-only observer for the pinned Quad150Nine build. The peer's UART PASS is
// independent; it never consults these internal signals. Emit only warm-loop PCs.
#include "VChipTop_TilePRCIDomain.h"
static void sample_quad(const VChipTop& t, uint64_t cycle) {
 const VChipTop_TilePRCIDomain* const tiles[]={t.__PVT__ChipTop__DOT__system__DOT__tile_prci_domain,t.__PVT__ChipTop__DOT__system__DOT__tile_prci_domain_1,t.__PVT__ChipTop__DOT__system__DOT__tile_prci_domain_2,t.__PVT__ChipTop__DOT__system__DOT__tile_prci_domain_3};
 for(unsigned hart=0;hart<4;++hart) {
  const auto& d=*tiles[hart];
#define FE(x) d.__PVT__element_reset_domain_rockettile__DOT__frontend__DOT__##x
#define CORE(x) d.__PVT__element_reset_domain_rockettile__DOT__core__DOT__##x
  const std::array<uint64_t,9> pcs{FE(_io_cpu_npc_T)<<1,FE(s1_pc),FE(s2_pc),FE(fq__DOT__elts_0_pc),CORE(aligned_pc),CORE(decoded_pc),CORE(ex_reg_pc),CORE(mem_reg_pc),CORE(wb_reg_pc)};
  const std::array<unsigned,9> valid{FE(s0_valid),FE(s1_valid),FE(s2_valid),FE(fq__DOT__valid_0),CORE(alignValid),CORE(decodeValid),CORE(ex_reg_valid),CORE(mem_reg_valid),CORE(wb_valid)};
  const bool issue_killed = CORE(ctrl_killd);
#undef FE
#undef CORE
  for(unsigned stage=0;stage<9;++stage) if(valid[stage] && pcs[stage]>=VCU_TRACE_LO && pcs[stage]<VCU_TRACE_HI)
   std::cout<<"TRACE "<<cycle<<' '<<hart<<' '<<stage<<' '<<pcs[stage] << (stage==5 && (pcs[stage]&2) && issue_killed ? " issue_killed" : "") <<'\n';
 }
}
