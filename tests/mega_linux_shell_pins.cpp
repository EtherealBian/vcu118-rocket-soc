// Host-only test of host TX: decode all three commands from the emitted 8N1
// pin levels. No DUT, OS, architectural or benchmark inference.
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
static void need(bool v,const char *msg){if(!v)throw std::runtime_error(msg);}
#include "mega_linux_shell.hpp"
int main(int argc,char **argv){
  need(argc==3,"args"); LinuxShell shell(argv[1],argv[2]);
  std::string uart; uint64_t tick=0; const unsigned p=1519;
  auto feed=[&](const std::string &s,bool entry=true){bool done=false;
    for(char c:s){uart+=c;done=shell.receive(uart,++tick,p,entry);}return done;};
  feed("\n# ");need(!shell.sent,"prompt before init");
  feed("\nLINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d\r\n# ",false);
  need(!shell.sent,"prompt before entry");
  for(unsigned j=0;j<3;++j){
    feed("\n# ");need(shell.sent==j+1 && shell.start==tick+4*p,"request pacing");
    auto fail=shell; bool rejected=false;try{fail.receive("\n"+shell.reply[j]+"\r\n",tick,p,true);}catch(const std::runtime_error&){rejected=true;}
    need(rejected,"accepted reply before TX");
    need(shell.pin(tick,p),"idle");
    uint64_t edge=shell.start;
    for(unsigned char c:shell.cmd[j]){
      for(unsigned bit=0;bit<24;++bit){bool val=bit>=9 || (bit && ((c>>(bit-1))&1));
        need(shell.pin(edge,p)==val && shell.pin(edge+p-1,p)==val,"8N1/idle pin error");edge+=p;}
    }
    need(shell.pin(edge,p) && shell.finish==edge,"idle after TX");tick=edge;
    feed(shell.cmd[j]);feed("\n# ");need(shell.sent==j+1 && shell.answered==j,"command echo was accepted");
    need(feed("\n"+shell.reply[j]+"\r\n")== (j==2),"wire done at wrong phase");
  }
  need(shell.sent==3&&shell.answered==3,"incomplete");
}
