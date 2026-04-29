; ISR entry stubs — one per IDT vector (0–255)
; Each stub pushes a dummy error code (for vectors that don't push one),
; then the vector number, saves all registers, and calls interrupt_dispatch().
; Vectors 8,10-14,17,21,29,30 push a real error code; all others push 0.

bits 64
extern interrupt_dispatch

; Macro: vector that does NOT push an error code
%macro ISR_NOERR 1
global isr_%1
isr_%1:
    push    qword 0         ; dummy error code
    push    qword %1        ; vector number
    jmp     isr_common
%endmacro

; Macro: vector that DOES push an error code (CPU already pushed it)
%macro ISR_ERR 1
global isr_%1
isr_%1:
    push    qword %1
    jmp     isr_common
%endmacro

; CPU exception stubs (0–31)
ISR_NOERR  0   ; divide by zero
ISR_NOERR  1   ; debug
ISR_NOERR  2   ; NMI
ISR_NOERR  3   ; breakpoint
ISR_NOERR  4   ; overflow
ISR_NOERR  5   ; bound range exceeded
ISR_NOERR  6   ; invalid opcode
ISR_NOERR  7   ; device not available
ISR_ERR    8   ; double fault          (error code = 0 always)
ISR_NOERR  9   ; coprocessor segment overrun (legacy)
ISR_ERR   10   ; invalid TSS
ISR_ERR   11   ; segment not present
ISR_ERR   12   ; stack-segment fault
ISR_ERR   13   ; general protection fault
ISR_ERR   14   ; page fault
ISR_NOERR 15   ; reserved
ISR_NOERR 16   ; x87 FPU exception
ISR_ERR   17   ; alignment check
ISR_NOERR 18   ; machine check
ISR_NOERR 19   ; SIMD FP exception
ISR_NOERR 20   ; virtualization exception
ISR_ERR   21   ; control protection exception
ISR_NOERR 22
ISR_NOERR 23
ISR_NOERR 24
ISR_NOERR 25
ISR_NOERR 26
ISR_NOERR 27
ISR_NOERR 28
ISR_ERR   29   ; HV injection exception
ISR_ERR   30   ; VMM communication exception
ISR_NOERR 31   ; security exception

; IRQ stubs (vectors 32–47, PIC-remapped)
%assign i 32
%rep 16
ISR_NOERR i
%assign i i+1
%endrep

; Fill remaining vectors 48–255 as no-error
%assign i 48
%rep 208
ISR_NOERR i
%assign i i+1
%endrep

section .text

; Common handler: save full integer + FPU/SSE state, call C dispatcher, restore
;
; Stack layout on entry (pushed by CPU + our stub):
;   [rsp+0]   r15
;   ...
;   [rsp+112] rax
;   [rsp+120] vector        (pushed by stub)
;   [rsp+128] error_code    (pushed by stub or CPU)
;   [rsp+136] rip           (pushed by CPU)
;   [rsp+144] cs
;   [rsp+152] rflags
;   [rsp+160] rsp (of interrupted context)
;   [rsp+168] ss
isr_common:
    ; ── 1. Save integer registers ─────────────────────────────────────────
    push    rax
    push    rbx
    push    rcx
    push    rdx
    push    rsi
    push    rdi
    push    rbp
    push    r8
    push    r9
    push    r10
    push    r11
    push    r12
    push    r13
    push    r14
    push    r15

    ; ── 2. Save x87 + MMX + SSE state ────────────────────────────────────
    ; FXSAVE64: saves x87 control/status/tag, ST0-ST7, XMM0-XMM15, MXCSR
    ; Must be done BEFORE calling any C code that might use float/SSE.
    ; GS base points at the current smp_cpu_t; its first field is a
    ; 16-byte-aligned 512-byte FXSAVE area.
    fxsave64 [gs:0]

    ; ── 3. Align stack to 16 bytes (System V ABI requirement for calls) ───
    ; After 15 pushes (120 bytes) + the 8 bytes for vector = 128 bytes
    ; from the CPU-pushed frame. 128 is already 16-byte aligned.
    ; However the stub pushed vector+error_code (16 bytes) before jumping
    ; here, so total displacement is 15*8+16 = 136. Stack may be misaligned.
    mov     rbp, rsp
    and     rsp, ~0xF       ; align down to 16-byte boundary

    ; ── 4. Call C dispatcher ─────────────────────────────────────────────
    ; interrupt_dispatch(vector, error_code, rip, cs, rflags, rsp)
    ; Arguments sourced from original (pre-alignment) stack via rbp:
    ;   vector      = [rbp + 120]
    ;   error_code  = [rbp + 128]
    ;   rip         = [rbp + 136]
    ;   cs          = [rbp + 144]
    ;   rflags      = [rbp + 152]
    ;   rsp         = [rbp + 160]
    mov     rdi, [rbp + 120]
    mov     rsi, [rbp + 128]
    mov     rdx, [rbp + 136]
    mov     rcx, [rbp + 144]
    mov     r8,  [rbp + 152]
    mov     r9,  [rbp + 160]

    call    interrupt_dispatch

    ; ── 5. Restore stack pointer ──────────────────────────────────────────
    mov     rsp, rbp

    ; ── 6. Restore FPU/SSE state ──────────────────────────────────────────
    fxrstor64 [gs:0]

    ; ── 7. Restore integer registers ─────────────────────────────────────
    pop     r15
    pop     r14
    pop     r13
    pop     r12
    pop     r11
    pop     r10
    pop     r9
    pop     r8
    pop     rbp
    pop     rdi
    pop     rsi
    pop     rdx
    pop     rcx
    pop     rbx
    pop     rax

    add     rsp, 16         ; discard vector + error_code pushed by stub
    iretq

section .note.GNU-stack noalloc noexec nowrite progbits
