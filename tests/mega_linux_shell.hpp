// Console driver for the stock functional model, not a serial-device driver.
// Three separate commands; wait for both the expanded reply and the next
// prompt before typing again. Never write DUT internals or inject console RX.
struct LinuxShell {
  std::array<std::string,3> cmd, reply;
  unsigned sent=0, answered=0;
  uint64_t start=0, finish=0;
  bool init=false;
  static constexpr unsigned slot=24; // 8N1, then 14 idle bit periods
  LinuxShell(const char *file,const std::string &nonce) {
    need(nonce.size()==14 && nonce.find_first_not_of("0123456789abcdef")==std::string::npos,"invalid shell challenge");
    std::ifstream in(file); std::string extra;
    for(auto &s:cmd){need(bool(std::getline(in,s)) && !s.empty() && s.size()<768 && s.find('\r')==s.npos,"invalid command file");s+='\n';}
    need(!std::getline(in,extra),"extra shell commands");
    reply={"CM_LIVE_42_"+nonce,"CM_MACHINE_END_42_"+nonce,"CM_DONE_42_"+nonce};
  }
  bool pin(uint64_t tick,unsigned p) const {
    if(!sent || tick<start || tick>=finish) return true;
    uint64_t b=(tick-start)/p; unsigned bit=b%slot;
    return bit>=9 || (bit && ((uint8_t(cmd[sent-1][b/slot])>>(bit-1))&1));
  }
  // Called only when the UART decoder has actually received a byte.
  bool receive(const std::string &uart,uint64_t tick,unsigned p,bool entry) {
    auto ends=[&](const std::string &s){return uart.size()>=s.size() && !uart.compare(uart.size()-s.size(),s.size(),s);};
    for(auto msg:{"Kernel panic","Oops:","SOC_SELFTEST_FAILED","LINUX_OSCHECK_FAILED","LINUX_DOT4_FAILED"})
      need(!ends(msg),"guest boot failure on console");
    if(ends("\nLINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d\r\n"))init=true;
    if(sent>answered && ends("\n"+reply[answered]+"\r\n")){
      need(tick>=finish-14ULL*p,"premature command reply");
      std::cerr<<"SHELL_REPLY tick="<<tick<<" step="<<sent<<"\n";
      if(++answered==3)return true;
    }
    if(init && entry && answered==sent && sent<3 && ends("\n# ")){
      start=tick+4*p;finish=start+cmd[sent].size()*slot*p;
      std::cerr<<"SHELL_TX tick="<<tick<<" step="<<sent+1<<" bytes="<<cmd[sent].size()<<"\n";++sent;
    }
    return false;
  }
};
