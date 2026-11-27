// Four-wide ChipTop, genuine ROM frame and privilege transition. Only external
// behavioral TL RAM is preloaded; no internal writes, UART shortcuts or SD.
#define main archived_chiptop_main
#include "rocket_chiptop.cpp"
#undef main
#include "VChipTop___024root.h"
#include <iterator>
#include <vector>
#define C(field)                                                                                   \
  (r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__core__DOT__##field)
struct EntryRx {
  unsigned period, edges = 0, bit = 0, value = 0;
  uint64_t last = 0, next = 0;
  bool prev = true, active = false;
  bool sample(bool pin, uint64_t tick, char &out) {
    bool got = false;
    if (pin != prev && edges < 10) {
      if (!edges)
        need(!pin, "first UART edge");
      else
        need(tick - last == period, "wrong UART bit interval");
      ++edges;
      last = tick;
    }
    if (!active && prev && !pin) {
      active = true;
      bit = value = 0;
      next = tick + period / 2;
    } else if (active && tick == next) {
      if (!bit)
        need(!pin, "bad UART start");
      else if (bit < 9)
        value |= unsigned(pin) << (bit - 1);
      else {
        need(pin, "bad UART stop");
        out = char(value);
        got = true;
        active = false;
      }
      ++bit;
      next += period;
    }
    prev = pin;
    return got;
  }
};
static std::string bytes(const char *name) {
  std::ifstream f(name, std::ios::binary);
  need(bool(f), "missing input");
  return {std::istreambuf_iterator<char>(f), {}};
}
// Commit row and FTQ operands refer to the same pre-edge RTL observation.
#define FQ(n)                                                                                      \
  (&r.ChipTop__DOT__system__DOT__tile_prci_domain__DOT__element_reset_domain_boom_tile__DOT__frontend__DOT__ftq__DOT__pcs_##n)
#define RANGE8(M, p, s)                                                                            \
  M(p, 0, s), M(p, 1, s), M(p, 2, s), M(p, 3, s), M(p, 4, s), M(p, 5, s), M(p, 6, s), M(p, 7, s)
#define RANGE32(M, p, s)                                                                           \
  RANGE8(M, p, s), M(p, 8, s), M(p, 9, s), M(p, 10, s), M(p, 11, s), M(p, 12, s), M(p, 13, s),     \
      M(p, 14, s), M(p, 15, s), M(p, 16, s), M(p, 17, s), M(p, 18, s), M(p, 19, s), M(p, 20, s),   \
      M(p, 21, s), M(p, 22, s), M(p, 23, s), M(p, 24, s), M(p, 25, s), M(p, 26, s), M(p, 27, s),   \
      M(p, 28, s), M(p, 29, s), M(p, 30, s), M(p, 31, s)
#define ADDR(p, n, s) &C(rob__DOT__rob_uop_##p##n##s)
#define FADDR(p, n, s) FQ(n)
#define BANKS(s)                                                                                   \
  {                                                                                                \
    {RANGE32(ADDR, , s)}, {RANGE32(ADDR, 1_, s)}, {RANGE32(ADDR, 2_, s)}, { RANGE32(ADDR, 3_, s) } \
  }
#define V(n) &C(_rob_io_commit_arch_valids_##n)
#define I(n) &C(_rob_io_commit_uops_##n##_ftq_idx)
int main(int argc, char **argv) {
  try {
    need(argc == 5, "usage: replay mem frame expected trace");
    const auto m = bytes(argv[1]), f = bytes(argv[2]);
    uint64_t expected = std::stoull(argv[3]);
    need(m.size() == 262144 && f.size() == 24 && f.substr(16) == m.substr(0, 8), "input");
    const unsigned period = 1519;
    const std::string ready = "UART5_READY v1\r\n", epoch = ready + "UART5_HANDOFF\r\n";
    Verilated::commandArgs(argc, argv);
    VChipTop t;
    TlMem ram;
    EntryRx rx{period};
    const auto &r = *t.rootp;
    for (size_t j = 8; j < m.size(); ++j)
      ram.mem.write(0x80000000 + j, uint8_t(m[j]));
    t.custom_boot = 0;
    t.jtag_TMS = 1;
    t.jtag_TDI = 0;
    t.spi_0_dq_0_i = 0;
    t.spi_0_dq_1_i = 1;
    t.spi_0_dq_2_i = 0;
    t.spi_0_dq_3_i = 0;
    const CData *const lo[4][32] = BANKS(_pc_lob);
    const CData *const edge[4][32] = BANKS(_edge_inst);
    const QData *const ftq[40] = {
        RANGE32(FADDR, , ), FQ(32), FQ(33), FQ(34), FQ(35), FQ(36), FQ(37), FQ(38), FQ(39)};
    const CData *const val[] = {V(0), V(1), V(2), V(3)}, *const idx[] = {I(0), I(1), I(2), I(3)};
    std::ofstream trace(argv[4], std::ios::binary);
    need(bool(trace), "open trace");
    std::vector<uint32_t> pre, post;
    std::vector<uint64_t> fence;
    bool active = false, done = false;
    uint64_t hot = 0;
    uint64_t send = 0, start = 0, stop = 0, n = 0, lanes[5]{};
    std::string uart;
    for (uint64_t i = 0; i < 4000000; ++i) {
      t.reset_io = i < 100;
      t.clock_uncore = 0;
      t.jtag_TCK = (i >> 3) & 1;
      t.uart_0_rxd = 1;
      if (send && i >= send && i - send < f.size() * 10u * period) {
        auto b = (i - send) / period;
        unsigned bit = b % 10;
        t.uart_0_rxd = bit == 9 || (bit && ((uint8_t(f[b / 10]) >> (bit - 1)) & 1));
      }
      ram.drive(t);
      t.eval();
      auto prv = C(csr__DOT__reg_mstatus_prv);
      auto epc = C(csr__DOT__reg_mepc);
      const bool ret = C(csr__DOT__insn_ret);
      if (!t.reset_io) {
        ram.sample(t);
        if (prv == 0 && start && !stop) {
          auto k = C(_rob_io_commit_arch_valids_0) + C(_rob_io_commit_arch_valids_1) +
                   C(_rob_io_commit_arch_valids_2) + C(_rob_io_commit_arch_valids_3);
          n += k;
          ++lanes[k];
          auto row = C(rob__DOT__com_idx);
          // Same reconstruction as the generated core CSR PC path: a 64-byte fetch block base,
          // six ROB low bits, and a two-byte correction for an instruction crossing a fetch edge.
          for (unsigned b = 0; b < 4; b++)
            if (*val[b]) {
              unsigned fidx = *idx[b];
              need(row < 32 && fidx < 40, "bad ROB/FTQ index");
              auto pc = ((*ftq[fidx] & ~UINT64_C(63)) + *lo[b][row]) - 2 * (*edge[b][row]);
              need(pc <= UINT32_MAX, "PC out of trace range");
              if (pc == 0x106b0) {
                need(!active && !done, "repeat start");
                active = true;
                fence.push_back(i);
              }
              if (pc == 0x10f3a) {
                need(active && !done, "bad end");
                done = true;
                active = false;
                fence.push_back(i);
              }
              if (active) {
                if (pc == 0x10af0)
                  fence.push_back(i);
                for (int j = 0; j < 4; ++j)
                  trace.put(char((pc >> (8 * j)) & 255));
                ++hot;
              } else {
                auto &side = done ? post : pre;
                need(side.size() < 32, "missing PC fence");
                side.push_back(pc);
              }
            }
        }
      }
      t.clock_uncore = 1;
      t.eval();
      if (i < 128)
        continue;
      need(t.spi_0_cs_0, "SD select");
      auto now = C(csr__DOT__reg_mstatus_prv);
      if (prv == 3 && now == 0) {
        std::cerr << "MRET tick=" << i << " epc=" << std::hex << epc << std::dec
                  << " ret=" << int(ret) << " satp=" << int(C(csr__DOT__reg_satp_mode))
                  << " uart_bytes=" << uart.size() << "\n";
        need(!start && ret && epc == 0x106b0 && C(csr__DOT__reg_satp_mode) == 8 && send &&
                 i >= send + 24 * 10 * period && uart.size() >= ready.size(),
             "unexpected MRET");
        start = i;
      }
      if (prv == 0 && now == 3) {
        stop = i;
        std::cerr << "EXIT start=" << start << " stop=" << stop << " cycles=" << stop - start
                  << " u_arch_valid=" << n << " mepc=" << std::hex << C(csr__DOT__reg_mepc)
                  << " cause=" << C(csr__DOT__reg_mcause) << " tval=" << C(csr__DOT__reg_mtval)
                  << std::dec << " lanes=";
        for (auto k : lanes)
          std::cerr << k << ",";
        std::cerr << "\n";
        need(start && C(csr__DOT__reg_mepc) == 0x147b4 && C(csr__DOT__reg_mcause) == 8,
             "unexpected user trap");
      }
      char ch;
      if (rx.sample(t.uart_0_txd, i, ch)) {
        uart += ch;
        std::cout.put(ch).flush();
        if (uart.size() <= epoch.size())
          need(epoch.compare(0, uart.size(), uart) == 0, "unexpected ROM output");
        if (uart == ready) {
          need(rx.edges == 10 && !send, "UART edges");
          send = i + 2 * period;
        }
        if (uart.size() > epoch.size()) {
          std::cerr << "WINDOW hot=" << hot << " pre=";
          for (auto x : pre)
            std::cerr << std::hex << x << ",";
          std::cerr << " post=";
          for (auto x : post)
            std::cerr << std::hex << x << ",";
          std::cerr << " fences=";
          for (auto x : fence)
            std::cerr << std::dec << x << ",";
          std::cerr << "\n";
          trace.close();
          need(bool(trace) && ch == 'K' && start && stop && done && hot == expected &&
                   fence.size() == 5 && n == hot + pre.size() + post.size(),
               "user state, fences or count mismatch");
          t.final();
          return 0;
        }
      }
    }
    throw std::runtime_error("budget exhausted");
  } catch (const std::exception &e) {
    std::cerr << "REPLAY_FAIL " << e.what() << "\n";
    return 1;
  }
}
