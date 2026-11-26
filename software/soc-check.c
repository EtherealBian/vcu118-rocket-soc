/* Linux userspace exercise; no physical addresses or reserved memory touched. */
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#define WORDS (4u*1024u*1024u)
static uint32_t pattern(uint32_t i, uint32_t round) { return (i*2654435761u) ^ (round*2246822519u); }
static time_t seconds(void) { struct timespec ts; if(clock_gettime(CLOCK_MONOTONIC,&ts)) {perror("clock_gettime"); exit(2);} return ts.tv_sec; }
int main(int argc,char **argv) {
 char *end=NULL; long duration=0; if(argc>2) return 2;
 if(argc==2) { errno=0; duration=strtol(argv[1],&end,10); if(errno || end==argv[1] || *end || duration<0 || duration>86400) return 2; }
 volatile uint32_t *ram=malloc(WORDS*sizeof(*ram)); if(!ram){perror("malloc");return 2;}
 volatile double a=1.5,b=2.5; if(a*b!=3.75) return 3;
 const time_t start=seconds(); uint32_t round=0;
 do { ++round; for(uint32_t i=0;i<WORDS;i++) ram[i]=pattern(i,round);
 for(uint32_t i=0;i<WORDS;i++) {uint32_t got=ram[i], want=pattern(i,round); if(got!=want){fprintf(stderr,"RAM mismatch word=%"PRIu32" expected=%08"PRIx32" got=%08"PRIx32"\n",i,want,got);return 1;}}
 } while(seconds()-start<duration);
 free((void*)ram); printf("SOC_CHECK_PASS bytes=%zu passes=%"PRIu32" elapsed_s=%ld\n",(size_t)WORDS*sizeof(uint32_t),round,(long)(seconds()-start)); return 0;
}
