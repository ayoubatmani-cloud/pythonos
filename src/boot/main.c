#include <stdint.h>
#include <stddef.h>
#include "gdt.h"
#include "idt.h"
#include "io.h"
#include "pit.h"
#include "fb.h"
#include "kthread.h"
#include "smp.h"
#include "tls.h"

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

static void serial_put_u32(uint32_t value) {
    char buf[11];
    int i = 0;
    if (value == 0) {
        serial_putc('0');
        return;
    }
    while (value && i < (int)sizeof(buf)) {
        buf[i++] = (char)('0' + (value % 10));
        value /= 10;
    }
    while (i > 0) {
        serial_putc(buf[--i]);
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

static uint8_t _tls_area[PYTHONOS_TLS_AREA_SIZE] __attribute__((aligned(16)));

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

    smp_bsp_early_init();
    serial_puts("[PythonOS] boot: BSP per-CPU state OK\n");

    idt_init();
    serial_puts("[PythonOS] boot: IDT OK\n");

    parse_mmap(mb2_info);
    serial_puts("[PythonOS] boot: memory map parsed\n");

    parse_mb2_framebuffer(mb2_info);
    if (boot_fb.valid)
        serial_puts("[PythonOS] boot: framebuffer found\n");

    fpu_init();
    serial_puts("[PythonOS] boot: FPU/SSE initialized\n");

    if (!tls_init_area(_tls_area, sizeof(_tls_area))) {
        serial_puts("[PythonOS] FATAL: TLS image does not fit boot area\n");
        for (;;) __asm__("hlt");
    }
    serial_puts("[PythonOS] boot: TLS initialized\n");

    serial_puts("[PythonOS] boot: kernel thread self-test");
    if (!kthread_selftest()) {
        serial_puts(" FAILED\n");
        for (;;) __asm__("hlt");
    }
    serial_puts(" OK\n");

    smp_init(mb2_info);
    serial_puts("[PythonOS] boot: SMP online ");
    serial_put_u32(smp_online_count());
    serial_puts("/");
    serial_put_u32(smp_cpu_count());
    serial_puts(" CPU(s), BSP APIC ID ");
    serial_put_u32(smp_bsp_apic_id());
    serial_puts("\n");
    serial_puts("[PythonOS] boot: SMP workers ");
    serial_put_u32(smp_worker_selftest_count());
    serial_puts("/");
    serial_put_u32(smp_online_count());
    serial_puts(" completed\n");

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
