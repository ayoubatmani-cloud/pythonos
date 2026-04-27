/* PythonOS kernel linker script — x86-64 higher-half kernel at 1 MiB */

ENTRY(_start)
OUTPUT_FORMAT(elf64-x86-64)

SECTIONS {
    . = 0x100000;   /* load at 1 MiB — above BIOS reserved region */

    .multiboot2 : {
        KEEP(*(.multiboot2))
    }

    .text ALIGN(4096) : {
        *(.text*)
    }

    .rodata ALIGN(4096) : {
        *(.rodata*)
    }

    .data ALIGN(4096) : {
        *(.data*)
    }

    .bss ALIGN(4096) : {
        *(COMMON)
        *(.bss*)
    }

    /* Discard debug info — keeps the image small */
    /DISCARD/ : {
        *(.comment)
        *(.eh_frame)
        *(.note*)
    }
}
