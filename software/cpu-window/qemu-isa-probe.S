/* QEMU virt ONLY. Check that the exact CPU model used to validate the portable
 * Linux image takes illegal-instruction traps for Zba and Zbb representatives. */
.option norvc
.section .text.init,"ax",@progbits
.globl _start
_start:
  la t0,trap
  csrw mtvec,t0
  li s0,0
  la s1,probe_zba
  li s2,3
  addi s2,s2,4
  li t0,7
  bne s2,t0,fail
  .option push
  .option arch,+zba,+zbb
probe_zba:
  sh1add t0,s2,s2
  li t0,1
  bne s0,t0,fail
  la s1,probe_zbb
probe_zbb:
  andn t0,s2,s2
  .option pop
  li t0,2
  bne s0,t0,fail
  la a0,ok
  j print
.balign 4
trap:
  csrr t0,mcause
  li t1,2
  bne t0,t1,fail
  csrr t0,mepc
  bne s1,t0,fail
  addi t0,t0,4
  csrw mepc,t0
  addi s0,s0,1
  mret
fail:
  la a0,bad
print:
  li t0,0x10000000
1: lbu t1,0(a0)
  beqz t1,2f
  sb t1,0(t0)
  addi a0,a0,1
  j 1b
2: li t0,0x100000
  li t1,0x5555
  sw t1,0(t0)
3: j 3b
.section .rodata
ok: .asciz "ISA_CONTROL_PASS addi=7 sh1add=illegal andn=illegal\n"
bad: .asciz "ISA_CONTROL_FAIL\n"
