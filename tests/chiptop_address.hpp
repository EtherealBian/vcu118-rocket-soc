// Monitor only the four guest-owned windows, at the ChipTop external TL port.
// Every dirty line must leave the cache and subsequently be refetched in each
// pass. A write-allocate Get before the first Put is not a data verification.
struct AddressAudit {
 struct State { unsigned puts=0, refills=0; };
 std::array<State,256> lines{};
 void request(uint32_t a,unsigned op,unsigned size) {
  if(a<0x81000000u)return;
  uint32_t off=a-0x81000000u; unsigned w=off>>29, in=off&0x1fffffffu;
  if(w>=4||in>=4096)return;
  need(size==6 && !(in&63u),"unexpected transfer width or alignment in address scratch");
  auto &l=lines[w*64+in/64];
  if(op==4) {if(l.refills<l.puts)++l.refills;}
  else {need(l.refills==l.puts && l.puts<2,"writeback repeated without a refetch");++l.puts;}
 }
 void verify() const {for(auto &l:lines)need(l.puts==2&&l.refills==2,"dirty writeback or external refetch missing");
  std::cerr<<"ADDRESS_EXTERNAL_TL_CONFIRMED lines=256 dirty_puts=512 ordered_refills=512\n";}
};
