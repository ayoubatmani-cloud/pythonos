; x86_64 AP startup trampoline.
;
; The BSP copies this 4 KiB page to AP_TRAMPOLINE_ADDR (0x8000), patches
; the magic slots below, and starts each AP with a SIPI vector of 0x08.

bits 16
org 0x8000

%define CODE64_SEL 0x08
%define DATA64_SEL 0x10

start:
    cli
    cld

    xor     ax, ax
    mov     ds, ax
    mov     es, ax
    mov     ss, ax
    mov     sp, 0x7000

    lgdt    [gdt64_ptr]

    mov     eax, cr4
    or      eax, (1 << 5)          ; PAE
    mov     cr4, eax

    mov     eax, dword [pml4_ptr]
    mov     cr3, eax

    mov     ecx, 0xC0000080        ; IA32_EFER
    rdmsr
    or      eax, (1 << 8)          ; LME
    wrmsr

    mov     eax, cr0
    or      eax, 0x80000001        ; PG | PE
    mov     cr0, eax

    jmp     CODE64_SEL:long_mode

bits 64
long_mode:
    mov     ax, DATA64_SEL
    mov     ds, ax
    mov     es, ax
    mov     fs, ax
    mov     gs, ax
    mov     ss, ax

    mov     rsp, [stack_top_ptr]
    and     rsp, -16
    xor     rbp, rbp

    mov     rdi, [cpu_arg_ptr]
    mov     rax, [entry_ptr]
    call    rax

.halt:
    cli
    hlt
    jmp     .halt

align 8
pml4_ptr:      dq 0x50594f534d503031  ; "PYOSMP01"
stack_top_ptr: dq 0x50594f534d503032  ; "PYOSMP02"
entry_ptr:     dq 0x50594f534d503033  ; "PYOSMP03"
cpu_arg_ptr:   dq 0x50594f534d503034  ; "PYOSMP04"

align 8
gdt64:
    dq 0
    dq 0x00AF9A000000FFFF            ; 64-bit kernel code
    dq 0x00AF92000000FFFF            ; 64-bit kernel data
gdt64_end:
gdt64_ptr:
    dw gdt64_end - gdt64 - 1
    dd gdt64

times 4096 - ($ - $$) db 0
