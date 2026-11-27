// Alternative external TL responder for the snapshot test. No internal RTL signals are driven.
// TlMem owns the original storage, A acceptance, beat counter and D response payload.
struct StrictWaitRam : TlMem {
  std::ofstream log;
  const unsigned extra;
  unsigned left = 0, charged = 0, count = 0;
  bool live = false, user = false;
  uint64_t request = 0, offer = 0, first = 0;
  StrictWaitRam(const char *name, unsigned n) : log(name), extra(n) {
    need(bool(log) && (n == 0 || n == 32), "expected private trace and 0/32 wait cycles");
    log << "accept_tick user opcode size source delay first_offer first_fire last_fire d_beats\n";
  }
  void drive(VChipTop &t) {
    TlMem::drive(t);
    if (left) {
      need(dvalid && !t.tl_slave_0_a_ready && beat == 0 && op == 4, "wait outside first read beat");
      t.tl_slave_0_d_valid = 0;
    }
  }
  void observe(const VChipTop &t, bool in_user, uint64_t tick) {
    const bool a = t.tl_slave_0_a_ready && t.tl_slave_0_a_valid;
    const bool d = t.tl_slave_0_d_valid && t.tl_slave_0_d_ready;
    const unsigned resp_beats = op == 4 ? beats : 1;
    if (left) {
      need(!a && !t.tl_slave_0_d_valid, "unexpected activity while waiting");
      --left;
    }
    if (t.tl_slave_0_d_valid) {
      need(live && !a && t.tl_slave_0_d_bits_source == src && t.tl_slave_0_d_bits_size == size,
           "unexpected D source/size or overlapping A");
      if (!offer) {
        offer = tick;
        need(offer == request + 1 + charged, "wrong A-to-first-D-offer interval");
      }
    }
    if (d) {
      if (!first) first = tick;
      ++count;
      if (count == resp_beats) {
        log << request << ' ' << user << ' ' << op << ' ' << size << ' ' << src << ' ' << charged
            << ' ' << offer << ' ' << first << ' ' << tick << ' ' << count << '\n';
        live = false;
      }
    }
    TlMem::sample(t);
    // For a multibeat Put, the reference responder enables D only after the final A beat.
    if (a && dvalid) {
      need(!live && !d, "response overwritten");
      live = true; user = in_user; charged = (user && op == 4) ? extra : 0;
      request = tick; left = charged; offer = first = count = 0;
    }
  }
  void finish(uint64_t tick) {
    log << "END " << tick << ' ' << live << ' ' << (live ? request : 0) << ' ' << pendingPut << '\n';
    log.close(); need(bool(log), "incomplete TL log");
  }
};
