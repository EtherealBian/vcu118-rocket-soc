/* Read-only mtime sampling in M mode. Return bounds in mcycle units for the
 * crossing of a specific tick, not a guess at the MMIO load latency. */
.option norvc
.section .text.init,"ax",@progbits
.globl _start
_start:
  csrci mstatus,8
  csrw mie,zero
  csrw mideleg,zero
  la t0,trap
  csrw mtvec,t0
  li s0,0x0200bff8   /* mtime */
  li s1,0x02004000   /* hart 0 mtimecmp */
  li s2,0x64000000   /* UART txdata */
  ld a0,0(s0)
  addi a0,a0,4
  jal ra,crossing
  mv s3,a1
  mv s4,a2
  addi a0,a0,256
  jal ra,crossing
  sub s5,a1,s4     /* latest start / earliest finish */
  sub s6,a2,s3     /* earliest start / latest finish */
  li t0,256000
  bgtu s5,t0,fail
  bltu s6,t0,fail
  li t0,255744     /* 256 * 999 must lie outside */
  bleu s5,t0,fail
  li t0,256256     /* likewise, 256 * 1001 */
  bgeu s6,t0,fail
  li s7,0
  ld s8,0(s0)
  addi s8,s8,8
  sd s8,0(s1)
  fence iorw,iorw
  li t0,128
  csrw mie,t0
  csrsi mstatus,8
spin:
  beqz s7,spin
  csrci mstatus,8
  li t0,1
  bne s7,t0,fail
  csrr t0,mip
  andi t0,t0,128
  bnez t0,fail
  li a0,84 /* T + two little-endian 32-bit bounds + K */
  jal ra,emit
  mv a3,s5
  jal s9,word
  mv a3,s6
  jal s9,word
  li a0,75
  j stop
.balign 4
trap:
  csrr t0,mcause
  li t1,0x8000000000000007
  bne t0,t1,fail
  bnez s7,fail
  ld t1,0(s0)
  bne t1,s8,fail /* handler within the same tick, only for this fixture */
  csrr t1,mip
  andi t1,t1,128
  beqz t1,fail
  li t1,-1
  sd t1,0(s1)
  fence iorw,iorw
clear:
  csrr t1,mip
  andi t1,t1,128
  bnez t1,clear
  addi s7,s7,1
  mret
crossing:
  li t4,0
sample:
  rdcycle t0
  fence iorw,iorw
  ld t1,0(s0)
  fence iorw,iorw
  rdcycle t2
  bgeu t1,a0,found
  mv t4,t0
  j sample
found:
  bne t1,a0,fail
  beqz t4,fail
  mv a1,t4
  mv a2,t2
  ret
word:
  li a4,4
byte:
  andi a0,a3,255
  jal ra,emit
  srli a3,a3,8
  addi a4,a4,-1
  bnez a4,byte
  jr s9
emit:
  lw t1,0(s2)
  bltz t1,emit
  sw a0,0(s2)
  ret
fail:
  li s2,0x64000000
  li a0,33
stop:
  jal ra,emit
1:wfi
  j 1b
