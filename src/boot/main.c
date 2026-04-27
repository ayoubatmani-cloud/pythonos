#include <stdint.h>
#include <stddef.h>
#include "gdt.h"
#include "idt.h"
#include "io.h"
#include "pit.h"
#include "fb.h"

// Minimal serial output for early boot debugging (COM1)
static void serial_putc(char c) {
    while ((inb(0x3F8 + 5) & 0x20) == 0) {}
    outb(0x3F8, c);
}

static void serial_puts(const char *s) {
    while (*s) {
        if (*s == '\n') serial_putc('\r');
        serial_putc(*s++);
    }
}

static void serial_init(void) {
    outb(0x3F8 + 1, 0x00); // disable interrupts
    outb(0x3F8 + 3, 0x80); // enable DLAB (baud rate divisor)
    outb(0x3F8 + 0, 0x03); // divisor lo: 38400 baud
    outb(0x3F8 + 1, 0x00); // divisor hi
    outb(0x3F8 + 3, 0x03); // 8N1, clear DLAB
    outb(0x3F8 + 2, 0xC7); // enable + clear FIFO, 14-byte threshold
    outb(0x3F8 + 4, 0x0B); // IRQs on, RTS/DSR set
}

// Multiboot2 structures (minimal — we only need the memory map tag)
typedef struct {
    uint32_t total_size;
    uint32_t reserved;
} mb2_info_t;

typedef struct {
    uint32_t type;
    uint32_t size;
} mb2_tag_t;

typedef struct {
    uint32_t type;
    uint32_t size;
    uint64_t base_addr;
    uint64_t length;
    uint32_t entry_type;    // 1=available, 3=ACPI, 4=hibernate, 5=defective
    uint32_t reserved;
} mb2_mmap_entry_t;

typedef struct {
    uint32_t type;          // = 6
    uint32_t size;
    uint32_t entry_size;
    uint32_t entry_version;
    mb2_mmap_entry_t entries[];
} mb2_mmap_tag_t;

// We export the memory map to Python as a flat array of (base, length) pairs
// for usable RAM only. Limited to 64 entries at boot.
#define MAX_MMAP_ENTRIES 64

typedef struct {
    uint64_t base;
    uint64_t length;
} mmap_entry_t;

static mmap_entry_t boot_mmap[MAX_MMAP_ENTRIES];
static int          boot_mmap_count = 0;

static void parse_mmap(mb2_info_t *mb2) {
    uint8_t *ptr = (uint8_t *)mb2 + 8;
    uint8_t *end = (uint8_t *)mb2 + mb2->total_size;

    while (ptr < end) {
        mb2_tag_t *tag = (mb2_tag_t *)ptr;
        if (tag->type == 0) break;  // end tag

        if (tag->type == 6) {       // memory map
            mb2_mmap_tag_t *mmap = (mb2_mmap_tag_t *)tag;
            uint32_t n = (mmap->size - 16) / mmap->entry_size;
            for (uint32_t i = 0; i < n && boot_mmap_count < MAX_MMAP_ENTRIES; i++) {
                mb2_mmap_entry_t *e = &mmap->entries[i];
                if (e->entry_type == 1) {  // usable RAM
                    boot_mmap[boot_mmap_count].base   = e->base_addr;
                    boot_mmap[boot_mmap_count].length = e->length;
                    boot_mmap_count++;
                }
            }
        }

        ptr += (tag->size + 7) & ~7;  // tags are 8-byte aligned
    }
}

// ── Thread-Local Storage setup ───────────────────────────────────────────────
// CPython 3.13 uses initial-exec TLS via %fs-relative addressing (e.g. %fs:-8).
// Without a valid FS base the first TLS access faults at 0xfffffffffffffff8.
// Allocate a small zeroed block and set IA32_FS_BASE (MSR 0xC0000100) to
// point 32 bytes in, giving 32 bytes of usable TLS below FS:0.
static uint8_t _tls_area[64] __attribute__((aligned(16)));

static void tls_init(void) {
    for (int i = 0; i < 64; i++) _tls_area[i] = 0;
    uintptr_t fs_base = (uintptr_t)&_tls_area[32];
    *(uint64_t *)fs_base = fs_base;   // self-pointer at FS:0 (glibc TCB convention)
    uint32_t lo = (uint32_t)(fs_base);
    uint32_t hi = (uint32_t)(fs_base >> 32);
    __asm__ volatile("wrmsr" : : "c"(0xC0000100U), "a"(lo), "d"(hi) : "memory");
}

// ── FPU / SSE initialization ─────────────────────────────────────────────────
static void fpu_init(void) {
    uint64_t cr0, cr4;

    // CR0: clear EM (no emulation), set MP (monitor coprocessor),
    //      clear TS (allow FPU access without #NM exception)
    __asm__ volatile ("mov %%cr0, %0" : "=r"(cr0));
    cr0 &= ~(1UL << 2);   // clear EM
    cr0 |=  (1UL << 1);   // set   MP
    cr0 &= ~(1UL << 3);   // clear TS
    __asm__ volatile ("mov %0, %%cr0" :: "r"(cr0) : "memory");

    // CR4: set OSFXSR (OS supports FXSAVE/FXRSTOR) and
    //           OSXMMEXCPT (OS handles #XM SIMD exceptions)
    __asm__ volatile ("mov %%cr4, %0" : "=r"(cr4));
    cr4 |= (1UL << 9);    // OSFXSR
    cr4 |= (1UL << 10);   // OSXMMEXCPT
    __asm__ volatile ("mov %0, %%cr4" :: "r"(cr4) : "memory");

    // Initialize x87 FPU to well-known state
    __asm__ volatile ("finit");

    // Set MXCSR: mask all SSE exceptions, round-to-nearest, flush-to-zero off
    uint32_t mxcsr = 0x1F80;   // mask: IM PM UM OM ZM DM; RC = 00 (RN)
    __asm__ volatile ("ldmxcsr %0" :: "m"(mxcsr) : "memory");
}

// Defined in hal/hal.c — sets up CPython and runs kernel.boot(mmap)
extern void python_kernel_start(mmap_entry_t *mmap, int mmap_count,
                                framebuffer_info_t *fb);

void kernel_main(uint32_t mb2_magic, mb2_info_t *mb2_info) {
    serial_init();
    serial_puts("[PythonOS] boot: serial OK\n");

    if (mb2_magic != 0x36d76289) {
        serial_puts("[PythonOS] FATAL: not loaded by a multiboot2 bootloader\n");
        for (;;) __asm__("hlt");
    }

    gdt_init();
    serial_puts("[PythonOS] boot: GDT OK\n");

    idt_init();
    serial_puts("[PythonOS] boot: IDT OK\n");

    parse_mmap(mb2_info);
    serial_puts("[PythonOS] boot: memory map parsed\n");

    parse_mb2_framebuffer(mb2_info);
    if (boot_fb.valid)
        serial_puts("[PythonOS] boot: framebuffer found\n");

    fpu_init();
    serial_puts("[PythonOS] boot: FPU/SSE initialized\n");

    tls_init();
    serial_puts("[PythonOS] boot: TLS initialized\n");

    // 100 Hz timer — fast enough for scheduling, slow enough to be cheap
    pit_init(100);
    serial_puts("[PythonOS] boot: PIT initialized at 100 Hz\n");

    __asm__ volatile ("sti");
    serial_puts("[PythonOS] boot: interrupts enabled\n");

    serial_puts("[PythonOS] boot: starting Python kernel\n");
    python_kernel_start(boot_mmap, boot_mmap_count, &boot_fb);

    serial_puts("[PythonOS] FATAL: python_kernel_start returned\n");
    for (;;) __asm__("hlt");
}
