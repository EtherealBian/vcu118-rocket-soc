/* Fixed working sets: arithmetic, load-to-use on one hot word, alternating branch. */
#include <stdint.h>
#define N 131072ul
#define UART ((volatile uint32_t*)0x64000000ul)
#define MTIME (*(volatile const uint64_t *)0x0200bff8ul)
struct result {uint64_t sum,cycles,inst;};
typedef void kernel(uint64_t,const uint64_t*,struct result*);
extern kernel chain_add,load_use,branch_alt;
static const uint64_t word=3;
static void ch(char c){while((int32_t)UART[0]<0){} UART[0]=(unsigned char)c;}
static void emit(const char*s){while(*s)ch(*s++);}
static void dec(uint64_t n){char d[22];unsigned i=0;do{d[i++]=(char)('0'+n%10);n/=10;}while(n);while(i)ch(d[--i]);}
static void field(const char*s,uint64_t n){emit(s);dec(n);}
static int run(kernel*fn,const char*name,uint64_t expect,uint64_t retired,unsigned round){
 struct result r;fn(128,&word,&r); /* do not include the warm-up or UART in the counter window */
 __asm__ volatile("fence iorw,iorw" ::: "memory");uint64_t t=MTIME;fn(N,&word,&r);uint64_t ticks=MTIME-t;
 emit("COUNTER ");emit(name);field(" round=",round);field(" result=",r.sum);field(" retired=",r.inst);field(" cycles=",r.cycles);field(" mtime=",ticks);emit("\r\n");
 return r.sum==expect && r.inst==retired && r.cycles>=r.inst && ticks>0;
}
void diagnose(void){UART[6]=867;UART[2]=1;emit("VCU118_COUNTER_START v1 n=131072\r\n");
 for(unsigned r=0;r<3;r++)if(!run(chain_add,"chain-add",N,3*N+1,r)||!run(load_use,"load-use",3*N,4*N+1,r)||!run(branch_alt,"branch-alt",N,4*N+N/2+1,r)){emit("VCU118_COUNTER_FAIL\r\n");return;}
 emit("VCU118_COUNTER_PASS kernels=3 rounds=3\r\n");}
