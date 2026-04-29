bits 64

section .rodata
align 16
global ap_trampoline_start
global ap_trampoline_end

ap_trampoline_start:
    incbin "build/boot/ap_trampoline.bin"
ap_trampoline_end:

section .note.GNU-stack noalloc noexec nowrite progbits
