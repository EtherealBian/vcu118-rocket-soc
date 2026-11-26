 .section .text.init,"ax",@progbits
 .global _start
_start:
 csrci mstatus,8
 .option push
 .option norelax
 la gp,__global_pointer$
 .option pop
 la sp,__stack_top
 call diagnose
1: wfi
 j 1b
