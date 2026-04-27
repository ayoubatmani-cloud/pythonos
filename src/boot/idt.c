#include "idt.h"
#include "io.h"
#include <stddef.h>

#define IDT_ENTRIES 256
#define KERNEL_CS   0x08

// Gate type: interrupt gate (clears IF on entry), ring 0, present
#define IDT_INTERRUPT_GATE 0x8E
// Gate type: trap gate (does NOT clear IF), ring 0, present
#define IDT_TRAP_GATE      0x8F

static idt_entry_t idt[IDT_ENTRIES];
static idt_ptr_t   idt_ptr;

// Forward declarations for all 256 ISR stubs (defined in isr_stubs.asm)
#define DECLARE_ISR(n) extern void isr_##n(void);
DECLARE_ISR(0)  DECLARE_ISR(1)  DECLARE_ISR(2)  DECLARE_ISR(3)
DECLARE_ISR(4)  DECLARE_ISR(5)  DECLARE_ISR(6)  DECLARE_ISR(7)
DECLARE_ISR(8)  DECLARE_ISR(9)  DECLARE_ISR(10) DECLARE_ISR(11)
DECLARE_ISR(12) DECLARE_ISR(13) DECLARE_ISR(14) DECLARE_ISR(15)
DECLARE_ISR(16) DECLARE_ISR(17) DECLARE_ISR(18) DECLARE_ISR(19)
DECLARE_ISR(20) DECLARE_ISR(21) DECLARE_ISR(22) DECLARE_ISR(23)
DECLARE_ISR(24) DECLARE_ISR(25) DECLARE_ISR(26) DECLARE_ISR(27)
DECLARE_ISR(28) DECLARE_ISR(29) DECLARE_ISR(30) DECLARE_ISR(31)
DECLARE_ISR(32) DECLARE_ISR(33) DECLARE_ISR(34) DECLARE_ISR(35)
DECLARE_ISR(36) DECLARE_ISR(37) DECLARE_ISR(38) DECLARE_ISR(39)
DECLARE_ISR(40) DECLARE_ISR(41) DECLARE_ISR(42) DECLARE_ISR(43)
DECLARE_ISR(44) DECLARE_ISR(45) DECLARE_ISR(46) DECLARE_ISR(47)

static void idt_set(int vector, void (*handler)(void), uint8_t type) {
    uint64_t addr = (uint64_t)handler;
    idt[vector].offset_low  = addr & 0xFFFF;
    idt[vector].selector    = KERNEL_CS;
    idt[vector].ist         = 0;
    idt[vector].type_attr   = type;
    idt[vector].offset_mid  = (addr >> 16) & 0xFFFF;
    idt[vector].offset_high = (addr >> 32) & 0xFFFFFFFF;
    idt[vector].reserved    = 0;
}

// Remap PIC: IRQ0-7 -> vectors 32-39, IRQ8-15 -> vectors 40-47
static void pic_remap(void) {
    // ICW1: start init, cascade, ICW4 needed
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x11), "Nd"((uint16_t)0x20));
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x11), "Nd"((uint16_t)0xA0));
    // ICW2: vector offsets
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x20), "Nd"((uint16_t)0x21)); // master -> 32
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x28), "Nd"((uint16_t)0xA1)); // slave  -> 40
    // ICW3: master has slave on IRQ2; slave id = 2
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x04), "Nd"((uint16_t)0x21));
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x02), "Nd"((uint16_t)0xA1));
    // ICW4: 8086 mode
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x01), "Nd"((uint16_t)0x21));
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x01), "Nd"((uint16_t)0xA1));
    // Mask all IRQs for now; drivers unmask as they initialize
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0xFF), "Nd"((uint16_t)0x21));
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0xFF), "Nd"((uint16_t)0xA1));
}

void idt_init(void) {
    idt_ptr.limit = sizeof(idt) - 1;
    idt_ptr.base  = (uint64_t)&idt;

    // CPU exceptions (0–21): trap gates so we can inspect state
    idt_set(0,  isr_0,  IDT_TRAP_GATE);
    idt_set(1,  isr_1,  IDT_TRAP_GATE);
    idt_set(2,  isr_2,  IDT_INTERRUPT_GATE);  // NMI
    idt_set(3,  isr_3,  IDT_TRAP_GATE);
    idt_set(4,  isr_4,  IDT_TRAP_GATE);
    idt_set(5,  isr_5,  IDT_TRAP_GATE);
    idt_set(6,  isr_6,  IDT_TRAP_GATE);
    idt_set(7,  isr_7,  IDT_TRAP_GATE);
    idt_set(8,  isr_8,  IDT_INTERRUPT_GATE);
    idt_set(9,  isr_9,  IDT_TRAP_GATE);
    idt_set(10, isr_10, IDT_TRAP_GATE);
    idt_set(11, isr_11, IDT_TRAP_GATE);
    idt_set(12, isr_12, IDT_TRAP_GATE);
    idt_set(13, isr_13, IDT_TRAP_GATE);
    idt_set(14, isr_14, IDT_INTERRUPT_GATE);  // page fault: interrupt gate (no nesting)
    idt_set(15, isr_15, IDT_TRAP_GATE);
    idt_set(16, isr_16, IDT_TRAP_GATE);
    idt_set(17, isr_17, IDT_TRAP_GATE);
    idt_set(18, isr_18, IDT_INTERRUPT_GATE);  // machine check
    idt_set(19, isr_19, IDT_TRAP_GATE);
    idt_set(20, isr_20, IDT_TRAP_GATE);
    idt_set(21, isr_21, IDT_TRAP_GATE);

    // Hardware IRQs (32–47): interrupt gates (auto-clear IF)
    idt_set(32, isr_32, IDT_INTERRUPT_GATE);
    idt_set(33, isr_33, IDT_INTERRUPT_GATE);
    idt_set(34, isr_34, IDT_INTERRUPT_GATE);
    idt_set(35, isr_35, IDT_INTERRUPT_GATE);
    idt_set(36, isr_36, IDT_INTERRUPT_GATE);
    idt_set(37, isr_37, IDT_INTERRUPT_GATE);
    idt_set(38, isr_38, IDT_INTERRUPT_GATE);
    idt_set(39, isr_39, IDT_INTERRUPT_GATE);
    idt_set(40, isr_40, IDT_INTERRUPT_GATE);
    idt_set(41, isr_41, IDT_INTERRUPT_GATE);
    idt_set(42, isr_42, IDT_INTERRUPT_GATE);
    idt_set(43, isr_43, IDT_INTERRUPT_GATE);
    idt_set(44, isr_44, IDT_INTERRUPT_GATE);
    idt_set(45, isr_45, IDT_INTERRUPT_GATE);
    idt_set(46, isr_46, IDT_INTERRUPT_GATE);
    idt_set(47, isr_47, IDT_INTERRUPT_GATE);

    pic_remap();

    __asm__ volatile ("lidt %0" :: "m"(idt_ptr));
}

// PIC end-of-interrupt
static inline void pic_eoi(uint64_t vector) {
    if (vector >= 40) // slave PIC
        __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x20), "Nd"((uint16_t)0xA0));
    __asm__ volatile ("outb %0, %1" :: "a"((uint8_t)0x20), "Nd"((uint16_t)0x20));
}

// ── Serial helpers for fault diagnostics (no libc available here) ────────────

static void _fault_putc(char c) {
    while ((inb(0x3F8 + 5) & 0x20) == 0) {}
    if (c == '\n') { while ((inb(0x3F8 + 5) & 0x20) == 0) {} outb(0x3F8, '\r'); }
    outb(0x3F8, (uint8_t)c);
}

static void _fault_puts(const char *s) {
    while (*s) _fault_putc(*s++);
}

static void _fault_hex(uint64_t v) {
    const char *d = "0123456789abcdef";
    char buf[19] = "0x0000000000000000";
    for (int i = 17; i >= 2; i--) { buf[i] = d[v & 0xf]; v >>= 4; }
    buf[18] = '\0';
    _fault_puts(buf);
}

static void _fault_byte(uint8_t v) {
    const char *d = "0123456789abcdef";
    char buf[3]; buf[0] = d[v >> 4]; buf[1] = d[v & 0xf]; buf[2] = '\0';
    _fault_puts(buf);
}

// Best-effort Python frame dump — heuristic, may be wrong for non-Python faults.
// Layout: f_executable(+0), previous(+8), f_funcobj(+16), f_globals(+24),
//         f_builtins(+32), f_locals(+40), frame_obj(+48), instr_ptr(+56),
//         stacktop(+64,int32), return_offset(+68,u16), owner(+70), localsplus[](+72)
static void _dump_py_frame(uint64_t maybe_frame) {
    if (maybe_frame < 0x100000 || maybe_frame >= 0x40000000ULL) return;
    uint64_t *f = (uint64_t *)maybe_frame;
    _fault_puts("\n  [PyFrame@"); _fault_hex(maybe_frame); _fault_puts("]");
    _fault_puts("\n    f_executable="); _fault_hex(f[0]);
    _fault_puts("  previous=");        _fault_hex(f[1]);
    _fault_puts("\n    instr_ptr=");   _fault_hex(f[7]);
    int32_t stacktop = *(int32_t *)((uint8_t *)f + 64);
    _fault_puts("  stacktop=");
    if (stacktop < 0) { _fault_putc('-'); _fault_hex((uint64_t)(-(int64_t)stacktop)); }
    else _fault_hex((uint64_t)stacktop);
    _fault_puts("\n    localsplus[0]="); _fault_hex(f[9]);
    _fault_puts("  [1]="); _fault_hex(f[10]);
    _fault_puts("  [2]="); _fault_hex(f[11]);
    // Bytecode near instr_ptr
    uint64_t iptr = f[7];
    if (iptr >= 0x100000 && iptr < 0x40000000ULL) {
        _fault_puts("\n    bytecode[-8..+8]:");
        uint8_t *bc = (uint8_t *)(iptr - 8);
        for (int i = 0; i < 17; i++) {
            if (i == 8) _fault_puts("|");
            _fault_putc(' '); _fault_byte(bc[i]);
        }
    }
}

static const char *_exc_name(uint64_t v) {
    static const char *n[] = {
        "#DE","#DB","NMI","#BP","#OF","#BR","#UD","#NM",
        "#DF","---","#TS","#NP","#SS","#GP","#PF","---",
        "#MF","#AC","#MC","#XF","#VE","#CP"
    };
    return (v < 22) ? n[v] : "???";
}

// ── CPU exception handler: always fatal, halts with serial diagnostics ────────

static void _fatal_exception(uint64_t vector, uint64_t error_code,
                              uint64_t rip, uint64_t rsp) {
    _fault_puts("\n[EXCEPTION] ");
    _fault_puts(_exc_name(vector));
    _fault_puts(" vec="); _fault_hex(vector);
    _fault_puts(" err="); _fault_hex(error_code);
    _fault_puts("\n  RIP="); _fault_hex(rip);
    _fault_puts("  RSP="); _fault_hex(rsp);

    if (vector == 14) {
        uint64_t cr2 = read_cr2();
        _fault_puts("  CR2="); _fault_hex(cr2);
        _fault_puts("\n  PF: ");
        _fault_puts((error_code & 1)  ? "prot "    : "not-present ");
        _fault_puts((error_code & 2)  ? "write "   : "read ");
        _fault_puts((error_code & 4)  ? "user "    : "kernel ");
        if (error_code & 8)  _fault_puts("rsvd-bit ");
        if (error_code & 16) _fault_puts("inst-fetch ");
    }

    // Dump 24 words from the faulting RSP and try to extract Python frame info.
    if (rsp && rsp < 0x40000000ULL) {
        uint64_t *sp = (uint64_t *)rsp;
        _fault_puts("\n  Stack:");
        for (int i = 0; i < 24; i++) {
            if (i % 4 == 0) { _fault_puts("\n   "); }
            _fault_hex(sp[i]); _fault_putc(' ');
        }
        // Heuristic: when crashing inside _PyEval_EvalFrameDefault call chain,
        // the Python frame pointer (r12) is typically saved at RSP+0x18.
        _dump_py_frame(sp[3]);   // RSP+0x18
        // Also try RSP+0x40 (Python stack pointer area), RSP+0x10
        if (sp[3] != sp[8]) _dump_py_frame(sp[8]);   // RSP+0x40
    }

    _fault_puts("\n[HALT]\n");
    __asm__ volatile("cli");
    for (;;) __asm__ volatile("hlt");
}

// Defined in Python bridge (hal.c); calls into kernel.interrupts.router
extern void interrupt_dispatch_python(uint64_t vector, uint64_t error_code,
                                      uint64_t rip, uint64_t cs,
                                      uint64_t rflags, uint64_t rsp);

void interrupt_dispatch(uint64_t vector, uint64_t error_code,
                        uint64_t rip, uint64_t cs,
                        uint64_t rflags, uint64_t rsp) {
    if (vector < 32)
        _fatal_exception(vector, error_code, rip, rsp);

    interrupt_dispatch_python(vector, error_code, rip, cs, rflags, rsp);

    if (vector >= 32 && vector <= 47)
        pic_eoi(vector);
}
