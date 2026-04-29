#pragma once
#include <stdint.h>

typedef struct {
    uint16_t offset_low;
    uint16_t selector;
    uint8_t  ist;           // interrupt stack table index (0 = none)
    uint8_t  type_attr;     // gate type + DPL + present bit
    uint16_t offset_mid;
    uint32_t offset_high;
    uint32_t reserved;
} __attribute__((packed)) idt_entry_t;

typedef struct {
    uint16_t limit;
    uint64_t base;
} __attribute__((packed)) idt_ptr_t;

// Called from asm stubs; dispatches into Python via interrupt_dispatch_python()
void interrupt_dispatch(uint64_t vector, uint64_t error_code,
                        uint64_t rip, uint64_t cs,
                        uint64_t rflags, uint64_t rsp);

void idt_init(void);
void idt_load(void);
