OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ram (rwx) : ORIGIN = 0x80000000, LENGTH = 8M }
PHDRS { code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
 .text : { KEEP(*(.text.init)) *(.text*) } > ram :code
 .rodata : { *(.srodata*) *(.rodata*) } > ram :code
 .data : { *(.data*) *(.sdata*) } > ram :data
 PROVIDE(__global_pointer$ = . + 0x800);
 .bss (NOLOAD) : { *(.sbss*) *(.bss*) *(COMMON) } > ram :data
 .stack (NOLOAD) : { . = ALIGN(16); . += 16384; __stack_top = .; } > ram :data
 /DISCARD/ : { *(.eh_frame*) *(.comment) }
}
