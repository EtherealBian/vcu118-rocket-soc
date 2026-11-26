/* The exact freestanding receiver runs with deterministic RX/mtime MMIO reads. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint64_t ticks;
static const uint8_t *wire;
static size_t left;
static unsigned idle, reads;
static int32_t rx(void){++reads;if(idle){--idle;return -1;}if(!left)return -1;--left;return *wire++;}
static uint64_t now(void){uint64_t old=ticks;ticks+=25000;return old;}
#define UART5_TEST_MMIO 1
#define UART5_RX_READ() rx()
#define UART5_NOW() now()
#include "../software/boot-uart/boot.c"
static uint8_t frame[]={ 'V','C','U','1','1','8','U','5',9,0,0,0,0x26,0x39,0xf4,0xcb,'1','2','3','4','5','6','7','8','9' };
static void check(const char *err,size_t n,unsigned first_idle,size_t changed){
    uint8_t buf[16];memset(buf,0xa5,sizeof(buf));wire=frame;left=n;idle=first_idle;reads=0;
    ticks=UINT64_MAX-50000;const char *reason=receive(buf+1);
    assert(err?(reason&&strcmp(reason,err)==0):!reason);
    assert(reads>=first_idle&&buf[0]==0xa5);
    assert(!memcmp(buf+1,frame+16,changed));
    for(size_t i=changed+1;i<sizeof(buf);i++)assert(buf[i]==0xa5);
}
int main(void){
    check(NULL,sizeof(frame),100,9); /* first byte may arrive far after 2s */
    frame[0]^=1;check("MAGIC",16,0,0);frame[0]^=1;
    frame[8]=0;check("LENGTH",16,0,0);frame[8]=9;
    frame[11]=2;check("LENGTH",16,0,0);frame[11]=0;
    frame[12]^=1;check("CRC",sizeof(frame),0,9);frame[12]^=1;
    check("TIMEOUT",1,0,0);check("TIMEOUT",15,0,0);check("TIMEOUT",17,0,1);
    puts("UART5_HOST_RECEIVER_PASS cases=8 (native C, synthetic time and RX, not RTL)");return 0;
}
