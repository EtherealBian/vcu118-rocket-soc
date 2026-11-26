/* Runs in M mode after the stock SD boot ROM. No writes outside our own DDR allocation. */
#include <stdint.h>
#define UART ((volatile uint32_t*)0x64000000UL)
#define MTIME (*(volatile const uint64_t*)0x0200bff8UL)
static volatile uint64_t scratch[131072] __attribute__((aligned(64)));
static void emit(char c) { while((int32_t)UART[0]<0) {} UART[0]=(uint32_t)c; }
static void line(const char *s) { while(*s) emit(*s++); emit('\r'); emit('\n'); }
static uint64_t ticks(void) { uint64_t r; __asm__ volatile("csrr %0, mcycle":"=r"(r)); return r; }
void diagnose(void) {
 UART[6]=867; UART[2]=1; line("VCU118_DIAG_START v1");
 for(unsigned pass=0;pass<2;pass++) {
  for(uint64_t i=0;i<131072;i++) scratch[i]=(i*0x9e3779b97f4a7c15ULL) ^ (~(uint64_t)0*pass);
  __asm__ volatile("fence rw,rw" ::: "memory");
  for(uint64_t i=0;i<131072;i++) if(scratch[i]!=((i*0x9e3779b97f4a7c15ULL) ^ (~(uint64_t)0*pass))) {line("VCU118_DIAG_FAIL memory");return;}
 }
 uint64_t t=MTIME, c=ticks(); while(MTIME==t) { if(ticks()-c>10000000ULL){line("VCU118_DIAG_FAIL mtime");return;}}
 line("VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced");
}
