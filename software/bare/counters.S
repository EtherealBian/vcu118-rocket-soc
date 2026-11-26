/* M-mode microkernels. Keep all counter reads and loop instructions visible in the ELF. */
.option push
.option norvc
.option norelax
.text
/* a0=iterations, a1=initialized word, a2=&{sum,cycles,retired}. */
.macro begin name
.balign 64
.global \name
.type \name,@function
\name:
 li t0,0
 csrr t1,mcycle
 csrr t2,minstret
.endm
.macro finish name
 csrr t3,minstret
 csrr t4,mcycle
 sub t4,t4,t1
 sub t3,t3,t2
 sd t0,0(a2)
 sd t4,8(a2)
 sd t3,16(a2)
 ret
.size \name,.-\name
.endm
begin chain_add
1: addi t0,t0,1
 addi a0,a0,-1
 bnez a0,1b
finish chain_add
begin load_use
1: ld t5,0(a1)
 add t0,t0,t5
 addi a0,a0,-1
 bnez a0,1b
finish load_use
begin branch_alt
1: andi t5,a0,1
 beqz t5,2f
 addi t0,t0,2
2: addi a0,a0,-1
 bnez a0,1b
finish branch_alt
.option pop
