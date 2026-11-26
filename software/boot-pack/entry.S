/* Linked for 0x84000000 but starts at the existing ROM5 entry 0x80000000.
 * Before relocation only PC-relative references to labels in this same image. */
.section .text.boot,"ax",@progbits
.globl _start
.option norelax
_start:
    csrci mstatus,8
    lla t0,_start
    lla t2,__copy_end
    li t1,0x84000000
    li t4,0x80000000
    bne t0,t4,.Lpark
.Lcopy:
    ld t3,0(t0)
    sd t3,0(t1)
    addi t0,t0,8
    addi t1,t1,8
    bltu t0,t2,.Lcopy
    fence rw,rw
    fence.i
    lla t0,.Lrelocated
    li t1,0x04000000
    add t0,t0,t1
    jr t0
.Lrelocated:
    li sp,0x87fff000
    mv s0,a0
    mv s1,a1
    mv a0,a1
    call unpack_boot
    beqz a0,.Lpark
    fence rw,rw
    fence.i
    mv a0,s0
    mv a1,s1
    li a2,0
    li t0,0x80000000
    jr t0
.Lpark:
    wfi
    j .Lpark
.section .note.GNU-stack,"",@progbits
