; PythonOS boot entry — Multiboot2 + long mode setup
; GRUB loads us in 32-bit protected mode. We set up paging, switch
; to 64-bit long mode, then call kernel_main() in C.

MULTIBOOT2_MAGIC    equ 0xE85250D6
MULTIBOOT2_ARCH     equ 0
MULTIBOOT2_LENGTH   equ (mb2_end - mb2_start)
MULTIBOOT2_CHECKSUM equ -(MULTIBOOT2_MAGIC + MULTIBOOT2_ARCH + MULTIBOOT2_LENGTH) & 0xFFFFFFFF

section .multiboot2
align 8
mb2_start:
    dd MULTIBOOT2_MAGIC
    dd MULTIBOOT2_ARCH
    dd MULTIBOOT2_LENGTH
    dd MULTIBOOT2_CHECKSUM
    ; Framebuffer tag — request linear framebuffer (type=5, size=20)
    dw 5        ; type: framebuffer
    dw 1        ; flags: bit 0 = optional
    dd 20       ; size (does not include inter-tag padding)
    dd 1024     ; width
    dd 768      ; height
    dd 32       ; depth
    ; 4 bytes padding: framebuffer tag ends at offset 36 (16+20),
    ; end tag must start at offset 40 (next 8-byte boundary).
    dd 0
    ; End tag (type=0, size=8)
    dw 0
    dw 0
    dd 8
mb2_end:

section .bss
align 16
stack_bottom:
    resb 4194304        ; 4 MiB stack — Python's compiler is deeply recursive
stack_top:

align 4096
boot_pml4:  resb 4096   ; Page Map Level 4
boot_pdpt:  resb 4096   ; Page Directory Pointer Table (covers 0–512 GiB, 1 GiB/entry)
boot_pd0:   resb 4096   ; PD for 0–1 GiB   (PDPT[0])
boot_pd1:   resb 4096   ; PD for 1–2 GiB   (PDPT[1])
boot_pd2:   resb 4096   ; PD for 2–3 GiB   (PDPT[2])
boot_pd3:   resb 4096   ; PD for 3–4 GiB   (PDPT[3], covers framebuffer at ~3.94 GiB)

; Saved in 32-bit mode, read in 64-bit mode. Using memory (not the stack)
; because push/pop sizes differ across the mode switch (4 bytes vs 8 bytes).
section .data
align 4
_mb2_magic: dd 0
_mb2_info:  dd 0

section .rodata
align 8
; Minimal 64-bit GDT for long mode entry
gdt64:
    dq 0                        ; null
    dq 0x00AF9A000000FFFF       ; 64-bit code (ring 0)
    dq 0x00AF92000000FFFF       ; 64-bit data (ring 0)
gdt64_end:
gdt64_ptr:
    dw (gdt64_end - gdt64 - 1)
    dd gdt64

section .text
bits 32
global _start
_start:
    mov esp, stack_top

    ; Save multiboot2 registers to memory before the mode switch.
    ; We cannot use push/pop across the 32→64-bit boundary because
    ; pop in 64-bit mode reads 8 bytes but push in 32-bit mode wrote 4.
    mov [_mb2_magic], eax
    mov [_mb2_info],  ebx

    ; Verify multiboot2 bootloader
    cmp eax, 0x36d76289
    jne .panic

    ; Enable PAE (required for 64-bit paging)
    mov eax, cr4
    or  eax, (1 << 5)
    mov cr4, eax

    call _setup_paging

    ; Load 64-bit GDT
    lgdt [gdt64_ptr]

    ; Set EFER.LME (long mode enable)
    mov ecx, 0xC0000080
    rdmsr
    or  eax, (1 << 8)
    wrmsr

    ; Enable paging — this activates long mode (EFER.LMA becomes 1)
    mov eax, cr0
    or  eax, (1 << 31) | 1
    mov cr0, eax

    ; Far jump into 64-bit code segment
    jmp 0x08:_long_mode_entry

.panic:
    cli
    hlt
    jmp .panic

_setup_paging:
    ; PML4[0] -> PDPT (present + writable)
    mov eax, boot_pdpt
    or  eax, 3
    mov [boot_pml4], eax

    ; PDPT[0..3] -> boot_pd0..3 (each covers 1 GiB)
    mov eax, boot_pd0
    or  eax, 3
    mov [boot_pdpt + 0], eax    ; 0–1 GiB

    mov eax, boot_pd1
    or  eax, 3
    mov [boot_pdpt + 8], eax    ; 1–2 GiB

    mov eax, boot_pd2
    or  eax, 3
    mov [boot_pdpt + 16], eax   ; 2–3 GiB

    mov eax, boot_pd3
    or  eax, 3
    mov [boot_pdpt + 24], eax   ; 3–4 GiB (framebuffer at ~3.94 GiB)

    ; Fill all 4 PDs: 4 × 512 huge-page entries = 4 GiB identity-mapped
    mov ecx, 0
    mov eax, 0x83           ; present + writable + huge (PS bit), phys=0
.map_2mb:
    ; Which PD does entry ecx belong to?
    mov edi, ecx
    and edi, 511            ; index within the 512-entry PD
    mov edx, ecx
    shr edx, 9             ; PD number (0–3)
    ; PD base = boot_pd0 + edx * 4096
    ; but we can use a jump table or just use 4-case logic
    ; Simpler: just compute boot_pd0 + (ecx * 8) since all 4 PDs are contiguous
    mov [boot_pd0 + ecx * 8], eax
    add eax, 0x200000       ; next 2 MiB page
    inc ecx
    cmp ecx, 2048           ; 4 GiB / 2 MiB = 2048 entries total
    jl  .map_2mb

    mov eax, boot_pml4
    mov cr3, eax
    ret

bits 64
_long_mode_entry:
    ; Reload data segments with 64-bit descriptor
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax

    ; Load multiboot2 args from memory: magic → rdi, info ptr → rsi.
    ; Writing the 32-bit sub-register (edi/esi) implicitly zeros the upper
    ; 32 bits of the full 64-bit register, giving correct zero-extension.
    xor rdi, rdi
    mov edi, [rel _mb2_magic]
    xor rsi, rsi
    mov esi, [rel _mb2_info]

    extern kernel_main
    call kernel_main

    ; kernel_main must never return
    cli
.halt:
    hlt
    jmp .halt

section .note.GNU-stack noalloc noexec nowrite progbits
