// Sample the stock ROB immediately before the rising edge; never drive the DUT.
// RANGE32 and C come from the sealed replay harness, Redirects owns dispatch tickets.
#define HEAD_BSY(p,n,s) &C(rob__DOT__rob_bsy_##p##n)
#define MASK4(name) (unsigned(C(name##0)) | unsigned(C(name##1))<<1 | unsigned(C(name##2))<<2 | unsigned(C(name##3))<<3)
struct HeadGaps : Redirects {
  std::ofstream heads;
  explicit HeadGaps(const std::string &prefix): Redirects(prefix),heads(prefix+".heads",std::ios::binary) {
    need(bool(heads),"open head trace");
  }
  template<class Root> void observe(const Root &r,uint32_t tick) {
    const CData *const bits[4][32]={{RANGE32(HEAD_BSY,,0)},{RANGE32(HEAD_BSY,1_,0)},
                                    {RANGE32(HEAD_BSY,2_,0)},{RANGE32(HEAD_BSY,3_,0)}};
    const unsigned row=C(rob__DOT__rob_head), valid=MASK4(rob__DOT__rob_head_vals_),
                   exc=MASK4(rob__DOT__can_throw_exception_), commit=MASK4(_rob_io_commit_valids_),
                   arch=MASK4(_rob_io_commit_arch_valids_);
    const bool csr=C(_csr_io_csr_stall), global=C(rob__DOT__block_commit);
    unsigned busy=0,expected=0,oldest=0; bool stop=global;
    need(row<32,"invalid head row");
    for (unsigned b=0;b<4;++b) if(valid&(1u<<b)) {
      if(!oldest){oldest=ticket[row*4+b];need(oldest && (oldest>>7)<tick,"head without prior dispatch");}
      if(*bits[b][row]) busy|=1u<<b;
      if(csr || ((exc|busy)&(1u<<b))) stop=true;
      if(!stop) expected|=1u<<b;
    }
    need(!(exc&~valid) && !(arch&~commit) && expected==commit,"actual head gates disagree with commit");
    if(arch) return;
    uint32_t word=row|(valid<<5)|(busy<<9)|(exc<<13)|(commit<<17)|(unsigned(csr)<<21)|(unsigned(global)<<22);
    for(uint32_t v:{tick,oldest,word}) for(int j=0;j<4;++j) heads.put(char(v>>(8*j)));
  }
  void finish(){heads.close();need(bool(heads),"unfinished head trace");Redirects::finish();}
};
#undef HEAD_BSY
#undef MASK4
