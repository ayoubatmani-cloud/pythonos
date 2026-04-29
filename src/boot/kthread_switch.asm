; Cooperative x86_64 kernel-thread context switch.
;
; void kthread_switch(uint64_t **old_rsp, uint64_t *new_rsp)
;   rdi = address of previous thread's saved RSP slot
;   rsi = next thread's saved RSP

bits 64
section .text

global kthread_switch
kthread_switch:
    push    rbp
    push    rbx
    push    r12
    push    r13
    push    r14
    push    r15

    mov     [rdi], rsp
    mov     rsp, rsi

    pop     r15
    pop     r14
    pop     r13
    pop     r12
    pop     rbx
    pop     rbp
    ret

section .note.GNU-stack noalloc noexec nowrite progbits
