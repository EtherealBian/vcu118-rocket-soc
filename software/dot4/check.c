#include <fcntl.h>
#include <sys/stat.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include "vcu_dot4_uapi.h"
#include "reference.h"
int main(int argc,char **argv){
 if(argc==2 && !strcmp(argv[1],"--if-present")){
  struct stat st;
  if(stat("/sys/firmware/devicetree/base",&st)){perror("cannot inspect live device tree");return 5;}
  if(stat("/sys/firmware/devicetree/base/soc/dot4@64002000",&st)){
   if(errno!=ENOENT){perror("dot4 DT lookup");return 5;}
   puts("LINUX_DOT4_NO_PLATFORM_DEVICE");return 0; /* QEMU/base SoC, not an accelerator pass */
  }
 }else if(argc!=1){fprintf(stderr,"usage: dot4-check [--if-present]\n");return 2;}
 int fd=open("/dev/vcu-dot4",O_RDWR);if(fd<0){perror("open accelerator");return 1;}uint32_t seed=0x54321;
 struct vcu_dot4_request q={.reserved=1};if(ioctl(fd,VCU_DOT4_EXEC,&q)!=-1||errno!=EINVAL){fprintf(stderr,"invalid reserved field accepted\n");return 2;}q.reserved=0;
 for(unsigned i=0;i<257;i++){uint32_t a,b;dot4_vec(i,&seed,&a,&b);q.a=a;q.b=b;if(ioctl(fd,VCU_DOT4_EXEC,&q)){perror("dot4 ioctl");return 3;}if(q.result!=dot4_ref(a,b)){fprintf(stderr,"vector %u mismatch got %d expected %d\n",i,q.result,dot4_ref(a,b));return 4;}}
 close(fd);puts("LINUX_DOT4_PASS vectors=257 reserved_rejected=1");return 0;}
