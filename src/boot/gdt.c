#include "gdt.h"
#include <stddef.h>

#define GDT_ENTRIES 5

static gdt_entry_t gdt[GDT_ENTRIES];
static gdt_ptr_t   gdt_ptr;

static void gdt_set(int i, uint32_t base, uint32_t limit, uint8_t access, uint8_t gran) {
    gdt[i].base_low   = base & 0xFFFF;
    gdt[i].base_mid   = (base >> 16) & 0xFF;
    gdt[i].base_high  = (base >> 24) & 0xFF;
    gdt[i].limit_low  = limit & 0xFFFF;
    gdt[i].granularity = ((limit >> 16) & 0x0F) | (gran & 0xF0);
    gdt[i].access     = access;
}

void gdt_load(void) {
    __asm__ volatile (
        "lgdt %0\n\t"
        "mov $0x10, %%ax\n\t"
        "mov %%ax, %%ds\n\t"
        "mov %%ax, %%es\n\t"
        "mov %%ax, %%fs\n\t"
        "mov %%ax, %%gs\n\t"
        "mov %%ax, %%ss\n\t"
        "pushq $0x08\n\t"
        "lea 1f(%%rip), %%rax\n\t"
        "pushq %%rax\n\t"
        "lretq\n\t"
        "1:\n\t"
        : : "m"(gdt_ptr) : "rax", "memory"
    );
}

void gdt_init(void) {
    gdt_ptr.limit = sizeof(gdt) - 1;
    gdt_ptr.base  = (uint64_t)&gdt;

    gdt_set(0, 0, 0,          0x00, 0x00);   // null
    gdt_set(1, 0, 0xFFFFFFFF, 0x9A, 0xAF);   // kernel code (64-bit)
    gdt_set(2, 0, 0xFFFFFFFF, 0x92, 0xAF);   // kernel data (64-bit)
    gdt_set(3, 0, 0xFFFFFFFF, 0xFA, 0xAF);   // user code   (64-bit, ring 3)
    gdt_set(4, 0, 0xFFFFFFFF, 0xF2, 0xAF);   // user data   (64-bit, ring 3)

    gdt_load();
}
