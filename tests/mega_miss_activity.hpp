// Read-only pre-edge observer of the recovery BOOM integer issue queue.
// Included after VChipTop___024root.h in a private copy of mega_user_replay.cpp.
#include "VChipTop_VcuIntMissSlot.h"
#include <array>
struct MissActivity {
  const VChipTop___024root &r;
  std::ofstream out;
#define IU(n) r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__core__DOT__int_issue_unit__DOT__##n
#define SLOT(n) r.__PVT__ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__core__DOT__int_issue_unit__DOT__slots_##n
#define EACH40(x) x(0),x(1),x(2),x(3),x(4),x(5),x(6),x(7),x(8),x(9),x(10),x(11),x(12),x(13),x(14),x(15),x(16),x(17),x(18),x(19),x(20),x(21),x(22),x(23),x(24),x(25),x(26),x(27),x(28),x(29),x(30),x(31),x(32),x(33),x(34),x(35),x(36),x(37),x(38),x(39)
#define GRANT(n) &IU(issue_slots_##n##_grant)
#define ACT(n) &IU(issue_slots_##n##_in_uop_valid)
  const std::array<const VChipTop_VcuIntMissSlot*,40> slots{EACH40(SLOT)};
  const std::array<const CData*,40> grants{EACH40(GRANT)}, moved{EACH40(ACT)};
  explicit MissActivity(const VChipTop___024root &root): r(root), out("moves.bin",std::ios::binary) {need(bool(out),"open miss trace");}
  void sample() {
    bool miss = r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT___lsu_io_core_ld_miss;
    bool base[43]{}, sensitive[43]{};
    uint8_t holes[42]{}, count=0;
    uint64_t residents=0, nominal=0, changes=0, observed=0;
    for(unsigned s=0;s<40;++s){
      const auto &slot=*slots[s]; const auto st=slot.__PVT__state;
      const bool vacates=*grants[s] && (st==1 || (st==2 && slot.__PVT__p1 && slot.__PVT__p2 && slot.__PVT__ppred));
      base[s]=st!=0 && !vacates;
      sensitive[s]=st!=0 && vacates && (slot.__PVT__p1_poisoned || slot.__PVT__p2_poisoned);
      residents |= uint64_t(sensitive[s])<<s;
      if(!st && count<4) ++count;
      holes[s]=count ? (1u<<(count-1)) : 0;
    }
    // Above the 40 resident slots, the dispatcher supplies unpoisoned inputs.
    base[40]=IU(will_be_valid_40); base[41]=IU(will_be_valid_41); base[42]=IU(will_be_valid_42);
    holes[40]=IU(next_40); holes[41]=IU(next_41);
    unsigned src8=0;
    for(unsigned d=0;d<39;++d){
      for(int j=4;j>=1;--j){
        if(holes[d+j-1]!=(1u<<(j-1))) continue;
        const unsigned s=d+j;
        nominal |= uint64_t(base[s])<<d; changes |= uint64_t(sensitive[s])<<d;
        if(d==8) src8=s;
        break;
      }
      observed |= uint64_t(*moved[d])<<d;
    }
    // All 39 actual DUT move-in valids must match on *every* sampled edge.
    need(observed==(nominal|(miss?changes:0)),"reconstructed integer move != actual DUT");
    // Fixed byte order: four 40-bit masks, then miss and the source selected for slot 8.
    uint8_t row[22]; size_t off=0;
    for(auto mask:{residents,nominal,changes,observed})
      for(unsigned b=0;b<5;++b) row[off++]=uint8_t(mask>>(8*b));
    row[20]=miss; row[21]=src8; out.write(reinterpret_cast<const char*>(row),sizeof(row));
  }
  void finish(){out.close();need(bool(out),"write miss trace");}
#undef GRANT
#undef ACT
#undef SLOT
#undef IU
#undef EACH40
};
