/* Diagnostic, not a CoreMark score: count cycles and retired instructions around
 * an unmodified upstream iterate() call. UART and initialization are outside. */
#include <stddef.h>
#include <stdint.h>
#include "coremark.h"

#define UART ((volatile uint32_t *)0x64000000ul)
#define ROUNDS 4u
static _Alignas(64) unsigned char buf[2000];
static volatile const uint16_t seeds[] = {0, 0x3415};
static void text(const char *s) { while (*s) {while ((int32_t)UART[0]<0) {} UART[0]=(unsigned char)*s++;} }
static void num(uint64_t x) {char t[24]; unsigned i=sizeof(t)-1; t[i]='\0'; do {t[--i]=(char)('0'+x%10);x/=10;}while(x);text(t+i);}
static void field(const char *s,uint64_t v){text(s);num(v);}
/* Input and complete mutable work area are reset before every window. */
static int one(unsigned k, unsigned sample) {
    core_results r = {0};
    for(size_t j=0;j<sizeof(buf);j++)buf[j]=0;
    r.seed1=seeds[k];r.seed2=r.seed1;r.seed3=0x66;r.execs=ALL_ALGORITHMS_MASK;
    r.size=sizeof(buf)/NUM_ALGORITHMS;r.iterations=ROUNDS;r.memblock[0]=buf;
    for(unsigned i=0;i<NUM_ALGORITHMS;i++)r.memblock[i+1]=buf+i*r.size;
    r.list=core_list_init(r.size,r.memblock[1],r.seed1);
    core_init_matrix(r.size,r.memblock[2],(int32_t)((uint32_t)(uint16_t)r.seed2<<16)|(uint16_t)r.seed1,&r.mat);
    core_init_state(r.size,r.seed1,r.memblock[3]);
    uint64_t c0,i0,c1,i1;
    __asm__ volatile ("fence rw,rw\n\tcsrr %0,mcycle\n\tcsrr %1,minstret" : "=&r"(c0),"=&r"(i0) :: "memory");
    iterate(&r);
    __asm__ volatile ("csrr %0,minstret\n\tcsrr %1,mcycle" : "=&r"(i1),"=&r"(c1) :: "memory");
    field("CPUWIN seed=",r.seed1);field(" sample=",sample);field(" iterations=",r.iterations);
    field(" cycles=",c1-c0);field(" retired=",i1-i0);field(" list=",r.crclist);field(" matrix=",r.crcmatrix);field(" state=",r.crcstate);field(" final=",r.crc);text("\r\n");
    return c1>c0 && i1>i0 && r.crclist==(k?0xe3c1:0xe714) && r.crcmatrix==(k?0x0747:0x1fd7) && r.crcstate==(k?0x8d84:0x8e3a) && r.crc==(k?EXPECTED_VALIDATION:EXPECTED_PERFORMANCE);
}
/* Freestanding compiler may lower aggregate initialization to this symbol. */
void *memset(void *p,int c,size_t n){volatile unsigned char *d=p;while(n--)*d++=(unsigned char)c;return p;}
void diagnose(void){UART[6]=867;UART[2]=1;text("CPUWIN_START v1 diagnostic_only\r\n");for(unsigned j=0;j<3;j++)for(unsigned k=0;k<2;k++)if(!one(k,j)){text("CPUWIN_FAIL\r\n");return;}text("CPUWIN_PASS sets=2 samples=3 not_a_score\r\n");}
