#ifndef VCU_DOT4_REFERENCE_H
#define VCU_DOT4_REFERENCE_H
#include <stdint.h>
static int32_t dot4_ref(uint32_t a,uint32_t b){int32_t total=0;for(unsigned i=0;i<4;i++){int x=a&255,y=b&255;total+=(x<128?x:x-256)*(y<128?y:y-256);a>>=8;b>>=8;}return total;}
static uint32_t dot4_rng(uint32_t *x){*x^=*x<<13;*x^=*x>>17;*x^=*x<<5;return *x;}
static void dot4_vec(unsigned i,uint32_t *seed,uint32_t *a,uint32_t *b){static const uint32_t k[][2]={{0,0},{0x80808080,0x80808080},{0x7f7f7f7f,0x7f7f7f7f},{0x80808080,0x7f7f7f7f},{0x807fff01,0x017f80ff}};if(i<sizeof(k)/sizeof(*k)){*a=k[i][0];*b=k[i][1];}else{*a=dot4_rng(seed);*b=dot4_rng(seed);}}
#endif
