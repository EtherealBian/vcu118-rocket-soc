/* UART ROM test, no stack or host-initialized shared memory. All shared state is
 * PROGBITS in the CRC-checked frame, not zero-fill assumed from the RAM model. */
.section .text.init,"ax",@progbits
.globl _start
.option norvc
_start:
  csrr s0,mhartid
  bne a0,s0,.Lbad
  li t0,4
  bgeu s0,t0,.Lbad
  bnez a2,.Lbad
  lwu t0,0(a1)
  li t1,0xedfe0dd0
  bne t0,t1,.Lbad
  la t0,.Ltrap
  csrw mtvec,t0
  li s1,1
  sll s1,s1,s0
  la s2,state
  amoor.w.aqrl zero,s1,(s2)
.Larrival:
  lw t0,0(s2)
  li t1,15
  bne t0,t1,.Larrival
  li t5,0
  li t4,32
  .balign 16
.Lwarm:
  .globl quad_trace_begin,quad_trace_end
quad_trace_begin:
  .rept 8
  addi t5,t5,1
  .endr
quad_trace_end:
  addi t4,t4,-1
  bnez t4,.Lwarm
  li t1,256
  bne t5,t1,.Lbad
  /* Test a real compressed instruction and an intentionally misaligned
     (halfword-aligned) 32-bit instruction in a taken/untaken branch region. */
  li t2,0
  .balign 4
  .option push
  .option rvc
  c.addi t2,1
  .option pop
  addi t2,t2,2
  li t3,3
  bne t2,t3,.Lbad
  li s4,0
  ecall
  li t0,1
  bne s4,t0,.Lbad
  mv s3,s0
.Lturn:
  lw t0,4(s2)
  bne t0,s3,.Lturn
  fence r,rw
  ld t2,8(s2)
  add t2,t2,s3
  addi t2,t2,1
  sd t2,8(s2)
  addi t1,s3,1
  fence rw,w
  sw t1,4(s2)
  addi s3,s3,4
  li t0,64
  bltu s3,t0,.Lturn
  addi t0,s2,16
  amoor.w.aqrl zero,s1,(t0)
  bnez s0,.Lpark
.Ldone:
  lw t1,16(s2)
  li t2,15
  bne t1,t2,.Ldone
  fence r,rw
  lw t1,4(s2)
  li t2,64
  bne t1,t2,.Lbad
  ld t1,8(s2)
  li t2,2080
  bne t1,t2,.Lbad
  la t0,pass
  li t2,0x64000000
.Lnext:
  lbu t1,0(t0)
  beqz t1,.Lpark
.Ltx:
  lw t3,0(t2)
  bltz t3,.Ltx
  sw t1,0(t2)
  addi t0,t0,1
  j .Lnext
.Lbad:
  j .Lbad
.Lpark:
  wfi
  j .Lpark
  .balign 4
.Ltrap:
  csrr t0,mcause
  li t1,11
  bne t0,t1,.Lbad
  csrr t0,mepc
  addi t0,t0,4
  csrw mepc,t0
  addi s4,s4,1
  mret
.section .rodata
pass: .asciz "QUAD_ROM_PASS harts=0,1,2,3 turns=64 sum=2080 traps=4\r\n"
.section .data
.balign 64
state: .word 0,0
       .dword 0
       .word 0
