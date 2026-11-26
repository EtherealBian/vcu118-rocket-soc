/* Linux RV64 syscall ABI, caller-save registers only. Keep FP state live during
 * blocking reads; each process has a distinct, exactly representable FP sequence. */
#include <asm/unistd.h>
.text
.balign 4
.globl fp_exchange
.type fp_exchange,@function
fp_exchange:
 addi sp,sp,-16
 mv t0,a0                        /* read fd */
 mv t1,a1                        /* write fd */
 mv t2,a2                        /* child? */
 mv t3,a3                        /* rounds */
 mv t4,a4                        /* shared uint64 */
 li t5,0                         /* round */
 slli t6,t2,8
 addi t6,t6,1                    /* parent 1, child 257 */
 fcvt.d.w ft0,t6
 fcvt.s.w ft1,t6
 li a5,1
 fcvt.d.w ft2,a5
 fcvt.s.w ft3,a5
.Lround:
 fadd.d ft0,ft0,ft2
 fadd.s ft1,ft1,ft3
 amoadd.d.aqrl zero,a5,(t4)
 bnez t2,.Lreceive
 xori a6,t5,0x55
 sb a6,0(sp)
 mv a0,t1
 mv a1,sp
 li a2,1
 li a7,__NR_write
 ecall
 bne a0,a5,.Lbad
.Lreceive:
 mv a0,t0
 mv a1,sp
 li a2,1
 li a7,__NR_read
 ecall
 bne a0,a5,.Lbad
 lbu a0,0(sp)
 beqz t2,.Lparent
 xori a6,t5,0x55
 bne a0,a6,.Lbad
 xori a6,t5,0x2a
 sb a6,0(sp)
 mv a0,t1
 mv a1,sp
 li a2,1
 li a7,__NR_write
 ecall
 bne a0,a5,.Lbad
 j .Lcheck
.Lparent:
 xori a6,t5,0x2a
 bne a0,a6,.Lbad
.Lcheck:
 addi t6,t6,1
 fcvt.d.w ft4,t6
 fcvt.s.w ft5,t6
 feq.d a0,ft0,ft4
 beqz a0,.Lbad
 feq.s a0,ft1,ft5
 beqz a0,.Lbad
 addi t5,t5,1
 bltu t5,t3,.Lround
 li a0,0
 j .Lreturn
.Lbad:
 li a0,1
.Lreturn:
 addi sp,sp,16
 ret
.size fp_exchange,.-fp_exchange
.section .note.GNU-stack,"",@progbits
