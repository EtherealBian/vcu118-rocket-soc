/* Linux U-mode: two address spaces, one shared counter and deterministic pipe handoffs.
 * Does not request privilege, open devices, or write persistent storage. */
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#define ROUNDS 64
static volatile unsigned char cow[4096] __attribute__((aligned(4096)));
extern int fp_exchange(int read_fd, int write_fd, int child, unsigned rounds, uint64_t *shared);
static unsigned char byte(unsigned i,int who){return (unsigned char)(i*37u+who*71u);}
static int page_is(int who){for(unsigned i=0;i<sizeof cow;i++)if(cow[i]!=byte(i,who))return 0;return 1;}
static void set_page(int who){for(unsigned i=0;i<sizeof cow;i++)cow[i]=byte(i,who);}
int main(void){
 int forward[2],back[2];uint64_t *shared=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_ANONYMOUS,-1,0);
 if(shared==MAP_FAILED||pipe(forward)||pipe(back))return 1;
 set_page(0);*shared=0;pid_t pid=fork();if(pid<0)return 2;
 int child=(pid==0), rfd=child?forward[0]:back[0], wfd=child?back[1]:forward[1];
 close(child?forward[1]:forward[0]);close(child?back[0]:back[1]);alarm(20);
 if(!page_is(0))return 3;
 set_page(1+child);
 int ok=fp_exchange(rfd,wfd,child,ROUNDS,shared)==0 && page_is(1+child);
 close(rfd);close(wfd);
 if(child)_exit(ok?0:4);
 int status=0; if(waitpid(pid,&status,0)!=pid || !WIFEXITED(status) || WEXITSTATUS(status)!=0 || !ok || *shared!=2*ROUNDS || !page_is(1))return 5;
 alarm(0);if(munmap(shared,4096))return 6;
 puts("LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d");return 0;
}
