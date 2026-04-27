/* boot_arm64.S — AArch64 bare-metal entry for PythonOS/QEMU virt
 * QEMU starts us at EL2, AArch64, MMU off, x0 = DTB pointer */

.section .text.boot, "ax"
.global _start
_start:
    mov     x19, x0          /* save DTB pointer across EL drop */

    /* Determine current EL */
    mrs     x0,  CurrentEL
    lsr     x0,  x0, #2
    cmp     x0,  #2
    bne     .Lat_el1         /* already EL1, skip drop */

.Lat_el2:
    /* Tell EL2 that EL1 is 64-bit AArch64 */
    mov     x0, #(1 << 31)
    msr     hcr_el2, x0

    /* Set EL1 entry via ELR_EL2 */
    adr     x0, .Lat_el1
    msr     elr_el2, x0

    /* SPSR_EL2: return to EL1h, all exceptions masked */
    mov     x0, #0x3c5
    msr     spsr_el2, x0

    /* Zero SCTLR_EL1 before drop */
    msr     sctlr_el1, xzr
    isb

    eret

.Lat_el1:
    /* Enable FPU/SIMD — clear FPEN trap in CPACR_EL1 */
    mrs     x0, cpacr_el1
    orr     x0, x0, #(3 << 20)
    msr     cpacr_el1, x0
    isb

    /* Set up stack */
    ldr     x0, =stack_top
    mov     sp, x0

    /* Zero BSS */
    ldr     x1, =bss_start
    ldr     x2, =bss_end
.Lzero_bss:
    cmp     x1, x2
    bge     .Ldone_bss
    str     xzr, [x1], #8
    b       .Lzero_bss
.Ldone_bss:

    /* Call C kernel entry */
    mov     x0, x19
    bl      kernel_main_arm64

.Lhalt:
    wfe
    b       .Lhalt

/* ── Exception vector table ────────────────────────────────────────────────
 * Must be aligned to 2KB (0x800).  AArch64 layout:
 *   0x000–0x180  EL1t (SP_EL0): sync / IRQ / FIQ / SError
 *   0x200–0x380  EL1h (SP_EL1): sync / IRQ / FIQ / SError  ← IRQ used here
 *   0x400–0x580  Lower EL, AArch64
 *   0x600–0x780  Lower EL, AArch32
 * ─────────────────────────────────────────────────────────────────────────── */

/*
 * Save/restore all general-purpose registers that the interrupted code
 * might be using.  We save x0–x18 (caller-saved by ABI) plus x29 (FP) and
 * x30 (LR) so that the C handler can make arbitrary calls without corrupting
 * the interrupted thread's register state.  x19–x28 are callee-saved; the C
 * handler preserves them itself.
 */
.macro save_caller_regs
    sub     sp,  sp,  #11 * 16    /* 176 bytes, 16-byte aligned */
    stp     x0,  x1,  [sp, #0  * 16]
    stp     x2,  x3,  [sp, #1  * 16]
    stp     x4,  x5,  [sp, #2  * 16]
    stp     x6,  x7,  [sp, #3  * 16]
    stp     x8,  x9,  [sp, #4  * 16]
    stp     x10, x11, [sp, #5  * 16]
    stp     x12, x13, [sp, #6  * 16]
    stp     x14, x15, [sp, #7  * 16]
    stp     x16, x17, [sp, #8  * 16]
    stp     x18, x29, [sp, #9  * 16]   /* x18=platform, x29=FP */
    str     x30,      [sp, #10 * 16]   /* x30=LR */
.endm

.macro restore_caller_regs
    ldp     x0,  x1,  [sp, #0  * 16]
    ldp     x2,  x3,  [sp, #1  * 16]
    ldp     x4,  x5,  [sp, #2  * 16]
    ldp     x6,  x7,  [sp, #3  * 16]
    ldp     x8,  x9,  [sp, #4  * 16]
    ldp     x10, x11, [sp, #5  * 16]
    ldp     x12, x13, [sp, #6  * 16]
    ldp     x14, x15, [sp, #7  * 16]
    ldp     x16, x17, [sp, #8  * 16]
    ldp     x18, x29, [sp, #9  * 16]
    ldr     x30,      [sp, #10 * 16]
    add     sp,  sp,  #11 * 16
.endm

.balign 0x800
.global exception_vectors
exception_vectors:
    /* EL1t (using SP_EL0) */
    .balign 0x80;  b  .Lstub      /* 0x000 sync  */
    .balign 0x80;  b  .Lstub      /* 0x080 irq   */
    .balign 0x80;  b  .Lstub      /* 0x100 fiq   */
    .balign 0x80;  b  .Lstub      /* 0x180 serror */

    /* EL1h (using SP_EL1) — our kernel runs here */
    .balign 0x80;  b  .Lstub      /* 0x200 sync  */
    .balign 0x80;  b  el1h_irq    /* 0x280 irq   ← timer fires here */
    .balign 0x80;  b  .Lstub      /* 0x300 fiq   */
    .balign 0x80;  b  .Lstub      /* 0x380 serror */

    /* Lower EL AArch64 */
    .balign 0x80;  b  .Lstub      /* 0x400 */
    .balign 0x80;  b  .Lstub      /* 0x480 */
    .balign 0x80;  b  .Lstub      /* 0x500 */
    .balign 0x80;  b  .Lstub      /* 0x580 */

    /* Lower EL AArch32 */
    .balign 0x80;  b  .Lstub      /* 0x600 */
    .balign 0x80;  b  .Lstub      /* 0x680 */
    .balign 0x80;  b  .Lstub      /* 0x700 */
    .balign 0x80;  b  .Lstub      /* 0x780 */

/* IRQ handler: save caller-saved regs, call C, restore, eret */
el1h_irq:
    save_caller_regs
    bl      arm64_irq_handler
    restore_caller_regs
    eret

/* Stub for unhandled vectors — spin */
.Lstub:
    wfe
    b  .Lstub
