OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x84000000;
  .image : { KEEP(*(.text.boot)) *(.text .text.*) *(.rodata .rodata.*) *(.data .data.*) KEEP(*(.packed)) . = ALIGN(8); }
  __copy_end = .;
  .bss (NOLOAD) : { *(.sbss .bss .bss.* COMMON) }
  ASSERT(SIZEOF(.bss) == 0,"unexpected stage BSS")
  ASSERT(__copy_end - _start <= 30 * 1024 * 1024,"stage exceeds ROM5 transport limit")
  ASSERT(_start == 0x84000000,"bad stage entry")
  /DISCARD/ : { *(.comment .note .note.* .eh_frame*) }
}
