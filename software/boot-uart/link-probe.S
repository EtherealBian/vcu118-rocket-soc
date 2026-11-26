/* Tiny pin-level boot witness; deliberately inherit the ROM UART divider. */
.file "link-probe.S"
.section .text.init,"ax",@progbits
.globl _start
_start:
  bnez a0,2f
  lwu t0,0(a1)
  li t1,0xedfe0dd0
  bne t0,t1,2f
  li t0,0x64000000
1:lw t1,0(t0)
  bltz t1,1b
  li t1,'K'
  sw t1,0(t0)
2:wfi
  j 2b
