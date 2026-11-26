#include <stdint.h>
#include "reference.h"
#define REG ((volatile uint32_t*)0x64002000ul)
#define UART ((volatile uint32_t*)0x64000000ul)
static void line(const char *s){for(;*s;s++){while((int32_t)UART[0]<0){}UART[0]=*s;}while((int32_t)UART[0]<0){}UART[0]=13;while((int32_t)UART[0]<0){}UART[0]=10;}
static void barrier(void){__asm__ volatile("fence iorw,iorw":::"memory");}
static uint32_t read_mm(unsigned i){barrier();uint32_t v=REG[i];barrier();return v;}
static void write_mm(unsigned i,uint32_t v){barrier();REG[i]=v;barrier();}
void diagnose(void){UART[6]=867;UART[2]=1;line("DOT4_MMIO_START");uint32_t seed=0x54321;if(read_mm(0)!=0x34544f44u||read_mm(1)!=1){line("DOT4_FAIL ID/status");return;}
 write_mm(4,2);if(read_mm(1)!=5){line("DOT4_FAIL empty-pop");return;}write_mm(4,4);
 for(unsigned j=0;j<257;j++){uint32_t a,b;dot4_vec(j,&seed,&a,&b);write_mm(2,a);write_mm(3,b);write_mm(4,1);
  if(j==0){write_mm(4,1);if(!(read_mm(1)&4)){line("DOT4_FAIL duplicate");return;}write_mm(4,4);}
  unsigned budget=10000;while(!(read_mm(1)&2)&&--budget){}if(!budget||(int32_t)read_mm(5)!=dot4_ref(a,b)||read_mm(1)!=10){line("DOT4_FAIL result/status");return;}
  write_mm(4,2);if(read_mm(1)!=1){line("DOT4_FAIL pop");return;}}
 line("DOT4_MMIO_PASS vectors=257 protocol_errors_checked=2");}
