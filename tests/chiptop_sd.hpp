// Behavioral SPI/SDHC read-only fixture. Off-chip pins only; never acknowledges media writes.
// The capacity is that of the backing test file, not a claim of physical-card certification.
struct Sd {
 std::ifstream image;std::array<uint8_t,6> cmd{};unsigned ncmd=0,bits=0;uint8_t tx=255,rx=0;bool miso=true,previousClk=false,multi=false,active=false,app=false,crcOn=false;unsigned nextLba=0,blocks=0,sectors=0;int badLba=-1;std::deque<uint8_t> q;std::vector<unsigned> cmds;uint32_t firstMulti=~0u;unsigned payloadReads=0;
 explicit Sd(const char* p):image(p,std::ios::binary){need(bool(image),"open SD image");image.seekg(0,std::ios::end);auto len=image.tellg();need(len>=524288&&uint64_t(len)%524288==0,"card file not CSD granularity");sectors=uint64_t(len)/512;image.seekg(0);}
 static uint8_t crc7(const uint8_t *v,size_t n){uint8_t c=0;while(n--){unsigned b=*v++;for(int k=0;k<8;k++){c<<=1;if((c^b)&128)c^=9;b<<=1;}}return (c<<1)|1;}
 void packet(const uint8_t *p,unsigned count,bool fault=false){auto c=crc16(p,count)^(fault?1:0);q.push_back(255);q.push_back(254);q.insert(q.end(),p,p+count);q.push_back(c>>8);q.push_back(c&255);}
 void sector(unsigned lba){need(lba<sectors,"past card end");std::array<uint8_t,512> b;image.seekg(uint64_t(lba)*512);image.read((char*)b.data(),512);need(bool(image),"reading backing file");packet(b.data(),512,int(lba)==badLba);blocks++;if(lba>=34)payloadReads++;}
 void received(uint8_t b){if(ncmd==0&&(b&0xc0)!=0x40)return;cmd[ncmd++]=b;if(ncmd!=6)return;ncmd=0;unsigned c=cmd[0]&63;uint32_t arg=(uint32_t(cmd[1])<<24)|(uint32_t(cmd[2])<<16)|(uint32_t(cmd[3])<<8)|cmd[4];if(cmds.size()<256)cmds.push_back(c);bool ac=app;app=false;uint8_t idle=!active;
  if(c!=17||arg<37||arg%1024==0)std::cerr<<"SD "<<(ac?"A":"")<<"CMD"<<c<<" arg="<<arg<<"\n";
  auto send=[this](std::initializer_list<uint8_t>x){q.insert(q.end(),x);};if((crcOn||c==0||c==8)&&cmd[5]!=crc7(cmd.data(),5)){send({uint8_t(idle|8)});return;}
  switch(c){case 0:active=app=crcOn=multi=false;send({1});break;
   case 8:send({idle,0,0,uint8_t(arg>>8),uint8_t(arg)});break;
   case 55:app=true;send({idle});break;
   case 41:if(!ac){send({uint8_t(idle|4)});break;}active=true;send({0});break;
   case 58:send({idle,uint8_t(active?0xc0:0),0xff,0x80,0});break;
   case 59:crcOn=arg&1;send({idle});break;
   case 16:send({uint8_t(arg==512?idle:idle|64)});break;
   case 9:case 10:{if(idle){send({idle});break;}std::array<uint8_t,16> reg{};if(c==9){unsigned size=sectors/1024-1;reg={0x40,0x0e,0,0x32,0x51,0x59,0, uint8_t((size>>16)&63),uint8_t(size>>8),uint8_t(size),0x7f,0x80,0x0a,0x40,0x20,0};}else{reg={0x12,'S','M','V','C','U','1','8',0x10,0,0,0,1,1,0x71,0};}reg[15]=crc7(reg.data(),15);send({0});packet(reg.data(),16);break;}
   case 13:send({idle,0});if(ac&&!idle){std::array<uint8_t,64> s{};packet(s.data(),64);}break;
   case 51:if(ac&&!idle){std::array<uint8_t,8> scr={0,1,0,0,0,0,0,0};send({0});packet(scr.data(),8);}else send({uint8_t(idle|4)});break;
   case 17:case 18:if(idle||arg>=sectors){send({uint8_t(idle|32)});break;}send({0});if(c==17)sector(arg);else{if(firstMulti==~0u)firstMulti=arg;nextLba=arg;multi=true;}break;
   case 12:multi=false;q.clear();send({255,0,255});break;
   default:send({uint8_t(idle|4)});break; /* illegal/unimplemented, including SDIO, MMC and writes */}}
 uint8_t next(){if(q.empty()&&multi)sector(nextLba++);if(q.empty())return 255;auto x=q.front();q.pop_front();return x;}
 void pins(VChipTop &t){const bool clk=t.spi_0_sck;if(t.spi_0_cs_0){bits=ncmd=0;rx=0;tx=255;q.clear();multi=false;miso=true;}else{
   if(clk&&!previousClk){rx=uint8_t((rx<<1)|(t.spi_0_dq_0_o&1));if(++bits==8)received(rx);}
   if(!clk&&previousClk){if(bits==8){bits=0;rx=0;tx=next();}else tx<<=1;}
   miso=tx>>7;}previousClk=clk;}
};
