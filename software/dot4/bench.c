/* Compare one scalar implementation with the v1 MMIO ABI, including the full
 * host-side protocol, on identical warmed inputs. No UART in either window. */
#include <stdint.h>
#include "reference.h"
#define N 257
#define UART ((volatile uint32_t *)0x64000000ul)
#define REG ((volatile uint32_t *)0x64002000ul)
#define TIME (*(volatile const uint64_t *)0x0200bff8ul)
struct pair { uint32_t a,b; };
static struct pair in[N]; static int32_t scalar_out[N],device_out[N],expected[N];
static inline void fence(void){__asm__ volatile("fence iorw,iorw" ::: "memory");}
static inline void wr(unsigned reg,uint32_t x){REG[reg]=x;fence();}
static inline uint32_t rd(unsigned reg){uint32_t v=REG[reg];fence();return v;}
static inline uint64_t cycles(void){uint64_t v;__asm__ volatile("csrr %0,mcycle":"=r"(v)::"memory");return v;}
static inline uint64_t inst(void){uint64_t v;__asm__ volatile("csrr %0,minstret":"=r"(v)::"memory");return v;}
static inline int32_t lane(uint32_t v,unsigned shift){return (int8_t)(v>>shift);}
static __attribute__((noinline,noclone)) int scalar(unsigned n){
 for(unsigned j=0;j<n;j++){uint32_t a=in[j].a,b=in[j].b;scalar_out[j]=lane(a,0)*lane(b,0)+lane(a,8)*lane(b,8)+lane(a,16)*lane(b,16)+lane(a,24)*lane(b,24);}return 1;
}
static __attribute__((noinline,noclone)) int device(unsigned n){
 for(unsigned j=0;j<n;j++){wr(2,in[j].a);wr(3,in[j].b);wr(4,1);unsigned left=1024;uint32_t s;
  do{s=rd(1);}while(!(s&2)&&--left);if(s!=10)return 0;device_out[j]=(int32_t)rd(5);wr(4,2);
 }return rd(1)==1;
}
static void ch(char c){while((int32_t)UART[0]<0){}UART[0]=(unsigned char)c;}
static void text(const char*s){while(*s)ch(*s++);}
static void field(const char*k,uint64_t x){char d[22];unsigned n=0;text(k);do{d[n++]=(char)('0'+x%10);x/=10;}while(x);while(n)ch(d[--n]);}
static int measured(int use_dev,unsigned round){
 int32_t *out=use_dev?device_out:scalar_out;for(unsigned j=0;j<N;j++)out[j]=~expected[j];
 fence();uint64_t time=TIME,c=cycles(),i=inst();int ok=use_dev?device(N):scalar(N);fence();i=inst()-i;c=cycles()-c;time=TIME-time;
 if(!ok||!i||c<i||!time)return 0;
 uint32_t sum=2166136261u;for(unsigned j=0;j<N;j++){if(out[j]!=expected[j])return 0;sum=(sum^(uint32_t)out[j])*16777619u;}
 text(use_dev?"DOTBENCH mmio":"DOTBENCH scalar");field(" round=",round);field(" checksum=",sum);field(" retired=",i);field(" cycles=",c);field(" mtime=",time);text("\r\n");return 1;
}
void diagnose(void){UART[6]=867;UART[2]=1;text("DOTBENCH_START v1 vectors=257\r\n");uint32_t seed=0x54321;
 for(unsigned j=0;j<N;j++){dot4_vec(j,&seed,&in[j].a,&in[j].b);expected[j]=dot4_ref(in[j].a,in[j].b);}if(rd(0)!=0x34544f44u||rd(1)!=1||!scalar(N)||!device(N))goto bad;
 for(unsigned r=0;r<4;r++)if(!measured(r&1,r)||!measured(!(r&1),r))goto bad;
 text("DOTBENCH_PASS vectors=257 rounds=4\r\n");return;
bad: text("DOTBENCH_FAIL\r\n");
}
