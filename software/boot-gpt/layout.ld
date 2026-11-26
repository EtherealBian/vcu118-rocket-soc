OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x10000;
  .boot : { KEEP(*(.text.start)) *(.text .text.*) *(.srodata .srodata.* .rodata .rodata.*) BYTE(0); . = ALIGN(8); dtb = .; }
  .forbidden : { *(.data .data.* .sdata .sdata.* .bss .bss.* .sbss .sbss.* COMMON) }
  ASSERT(SIZEOF(.forbidden) == 0, "writable static storage forbidden")
  ASSERT(SIZEOF(.boot) <= 4312, "code no longer fits beside pinned DTB")
  /DISCARD/ : { *(.eh_frame*) *(.comment*) *(.note*) }
}
