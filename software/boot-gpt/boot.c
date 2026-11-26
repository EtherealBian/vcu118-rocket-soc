/* VCU118 single-hart diagnostic bootloader; GPT and wire CRCs detect errors, not forgery.
 * Board contract: 100 MHz peripheral clock; SDHC, SPI mode 0; primary GPT only.
 * Scratch and stack reside outside the entire 30 MiB load window. */
#include <stdint.h>
#define SPI ((volatile uint32_t*)0x64001000ul)
#define UART ((volatile uint32_t*)0x64000000ul)
#define RAM ((uint8_t*)0x80000000ul)
#define TICKS (*(volatile const uint64_t*)0x0200bff8ul) /* 100 kHz */
#define FIRST 34u
#define MAX_SECTORS 61440u
static void line(const char *s){while(*s){while((int32_t)UART[0]<0){} UART[0]=(unsigned char)*s++;}}
static int fail(const char *s){line("ROM4_STOP ");line(s);line("\r\n");return -1;}
/* Hardware serializes one outstanding byte. A raw transfer that cannot finish is fatal. */
static unsigned xfer(unsigned x){SPI[0x48/4]=x;int32_t r;unsigned budget=100000;
 do {r=SPI[0x4c/4];if(r>=0)return r&255;}while(--budget);
 fail("SPI_FIFO");for(;;)__asm__ volatile("wfi");}
static void deselect(void){SPI[0x18/4]=3;xfer(255);}
static unsigned command(unsigned c,uint32_t arg){uint8_t a[5]={64+c,arg>>24,arg>>16,arg>>8,arg};unsigned crc=0;
 SPI[0x18/4]=2;xfer(255);for(unsigned n=0;n<5;n++){unsigned b=a[n];xfer(b);for(unsigned k=0;k<8;k++){crc<<=1;if((crc^b)&128)crc^=9;b<<=1;}}xfer(((crc<<1)|1)&255);
 for(unsigned n=0;n<16;n++){unsigned r=xfer(255);if(r<128)return r;}return 255;}
static int initcard(void){SPI[0]=124;SPI[0x18/4]=3;for(unsigned n=0;n<12;n++)xfer(255);
 unsigned r=command(0,0);deselect();if(r!=1)return -1;
 r=command(8,0x1aa);uint32_t r7=0;for(unsigned n=0;n<4;n++)r7=(r7<<8)|xfer(255);deselect();if(r!=1||r7!=0x1aa)return -1;
 uint64_t start=TICKS;do{r=command(55,0);deselect();if(r!=1&&r!=0)return -1;r=command(41,0x40000000);deselect();if(r==0)break;if(r!=1||TICKS-start>150000)return -1;}while(1);
 r=command(58,0);unsigned ocr=xfer(255);for(unsigned n=0;n<3;n++)xfer(255);deselect();if(r||(ocr&0xc0)!=0xc0)return -1;
 SPI[0]=3; /* 12.5 MHz: 100 MHz/(2*(3+1)). */ return 0;}
static unsigned crc16(unsigned crc,unsigned x){crc=((crc>>8)|(crc<<8))&65535;crc^=x;crc^=(crc>>4)&15;return (crc^(crc<<12)^((crc&255)<<5))&65535;}
static uint32_t crc32(uint32_t c,const uint8_t *b,unsigned n){while(n--){c^=*b++;for(int k=0;k<8;k++)c=(c>>1)^((0u-(c&1))&0xedb88320u);}return c;}
static uint32_t le32(const uint8_t *p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t le64(const uint8_t *p){return le32(p)|((uint64_t)le32(p+4)<<32);}
static int sector(uint32_t lba,uint8_t *dest){int rc=-1;if(command(17,lba)==0){uint64_t start=TICKS;unsigned tok;do{tok=xfer(255);if(tok!=255)break;}while(TICKS-start<50000);
 if(tok==254){unsigned c=0;for(unsigned n=0;n<512;n++){unsigned x=xfer(255);dest[n]=x;c=crc16(c,x);}unsigned received=xfer(255)<<8;received|=xfer(255);rc=(c==received)?0:-1;}}
 deselect();return rc;}
int load_gpt(void){uint8_t buf[512];UART[6]=867;UART[2]=1;line("ROM4_INIT\r\n");if(initcard())return fail("SD_INIT");
 if(sector(1,buf))return fail("GPT_IO");uint32_t hcrc=le32(buf+16),tcrc=le32(buf+88);for(int i=16;i<20;i++)buf[i]=0;
 if(le32(buf)!=0x20494645||le32(buf+4)!=0x54524150||le32(buf+8)!=0x10000||le32(buf+12)!=92||(~crc32(~0u,buf,92))!=hcrc||le64(buf+24)!=1||le64(buf+40)!=FIRST||le64(buf+72)!=2||le32(buf+80)!=128||le32(buf+84)!=128)return fail("GPT_HEADER");
 uint64_t usable_end=le64(buf+48),last=0;uint32_t running=~0u;
 for(unsigned i=0;i<32;i++){if(sector(2+i,buf))return fail("GPT_IO");running=crc32(running,buf,512);
  if(i==0){/* Same payload type as pinned Chipyard image recipes (GPT on-disk GUID). */
   if(le32(buf)!=0x7c3457ef||le32(buf+4)!=0x11aa0000||le32(buf+8)!=0x300011aa||le32(buf+12)!=0xacec4365||le64(buf+32)!=FIRST)return fail("GPT_ENTRY");last=le64(buf+40);}}
 if((~running)!=tcrc||last<FIRST||last>usable_end||last>=FIRST+MAX_SECTORS)return fail("GPT_BOUNDS_CRC");
 line("ROM4_LOAD\r\n");for(unsigned i=0;i<=last-FIRST;i++){if(sector(FIRST+i,RAM+(uint64_t)i*512))return fail("PAYLOAD_IO_CRC");}
 line("ROM4_HANDOFF\r\n");return 0;}
