/* Raw, uncompressed, SMP payloads only. The system reset clears all four CLINT MSIP bits. */
.section .text.start,"ax",@progbits
.globl _start
_start:
  csrw mie, zero
  csrr s0, mhartid
  li t0, 4
  bgeu s0,t0,.Lpark
  bnez s0,.Lwait
  li sp,0x8ffff000
  call load_uart
  bnez a0,.Lpark
  /* Publish verified DDR writes before signaling any secondary through MMIO. */
  fence iorw,iorw
  li t0,0x02000000
  li t1,1
  sw t1,0(t0)    /* boot barrier closed before any secondary can see a release */
  fence iorw,iorw
  sw t1,4(t0)
  sw t1,8(t0)
  sw t1,12(t0)
  fence iorw,iorw
.Lacks:
  lw t1,4(t0)
  lw t2,8(t0)
  or t1,t1,t2
  lw t2,12(t0)
  or t1,t1,t2
  bnez t1,.Lacks
  fence iorw,iorw
  sw zero,0(t0)   /* all ROM-owned release bits have been acknowledged */
  j .Lenter
.Lwait:
  li t0,0x02000000
  slli t1,s0,2
  add t0,t0,t1
.Lpoll:
  lw t1,0(t0)
  beqz t1,.Lpoll
  sw zero,0(t0)
  fence iorw,iorw
  li t0,0x02000000
.Lgate:
  lw t1,0(t0)
  bnez t1,.Lgate
.Lenter:
  fence iorw,iorw
  fence.i
  mv a0,s0
  la a1,dtb
  li a2,0
  li t0,0x80000000
  jr t0
.Lpark:
  wfi
  j .Lpark
