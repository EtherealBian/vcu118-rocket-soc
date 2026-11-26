/* Exclusive M-mode diagnostic for the 2 GiB VCU118 configuration. Never run under Linux.
 * Reserve the low 8 MiB linker region and the complete 8 MiB region containing the
 * former recovery-ROM stack. All tests use addressed, naturally aligned 64-bit CPU accesses. */
#include <stdint.h>
#define UART ((volatile uint32_t *)0x64000000ul)
#define MTIME (*(volatile const uint64_t *)0x0200bff8ul)
#define BLOCK_BYTES (8ul<<20)
#define RAM_BASE 0x80000000ul
static void ch(char c){while((int32_t)UART[0]<0){}UART[0]=(uint8_t)c;}
static void text(const char*s){while(*s)ch(*s++);}
static void decimal(uint64_t v){char b[22];unsigned n=0;do{b[n++]=(char)('0'+v%10);v/=10;}while(v);while(n)ch(b[--n]);}
static void field(const char* key,uint64_t n){text(key);decimal(n);}
static void barrier(void){__asm__ volatile("fence iorw,iorw" ::: "memory");}
static uint64_t mix(uint64_t word,unsigned pass){return (word*UINT64_C(0x9e3779b97f4a7c15))^(pass?UINT64_MAX:0);}
void diagnose(void){UART[6]=867;UART[2]=1;text("VCU118_SWEEP_START v1 block_mib=8 blocks=254\r\n");
 for(unsigned pass=0;pass<2;pass++)for(unsigned rd=0;rd<2;rd++){
  unsigned blocks=0;uint64_t start=MTIME;
  for(unsigned block=1;block<256;block++){
   if(block==31)continue;
   uintptr_t addr=RAM_BASE+block*BLOCK_BYTES;volatile uint64_t *p=(volatile uint64_t*)addr;
   for(unsigned long j=0;j<BLOCK_BYTES/sizeof(*p);j++){
    uint64_t expected=mix((addr>>3)+j,pass);
    if(rd){uint64_t got=p[j];if(got!=expected){text("VCU118_SWEEP_FAIL");field(" address=",addr+8*j);field(" pass=",pass);field(" expected=",expected);field(" got=",got);text("\r\n");return;}}
    else p[j]=expected;
   }
   blocks++;
   if(!(blocks%64)||blocks==254){barrier();text("SWEEP");field(" pass=",pass);text(rd?" read":" write");field(" blocks=",blocks);field(" ticks=",MTIME-start);text("\r\n");}
  }
  barrier();
 }
 text("VCU118_SWEEP_PASS bytes=2130706432 passes=2\r\n");
}
