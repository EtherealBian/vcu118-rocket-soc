/* Single-hart VCU118. No operating system, no writable ROM, no gp or BSS dependency. */
.section .text.start,"ax",@progbits
.globl _start
_start:
  csrw mie, zero
  csrr a0, mhartid
  bnez a0, .Lpark
  li sp, 0x8ffff000
  call load_gpt
  bnez a0, .Lpark
  fence rw,rw
  fence.i
  csrr a0, mhartid
  la a1, dtb
  li t0, 0x80000000
  jr t0
.Lpark:
  wfi
  j .Lpark
