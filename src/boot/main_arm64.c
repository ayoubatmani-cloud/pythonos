/*
 * main_arm64.c — AArch64 kernel entry after boot assembly.
 *
 * Sets up paging (identity map), TLS, GIC, generic timer, then starts Python.
 * QEMU virt machine: RAM at 0x40000000, PL011 at 0x09000000.
 */

#include <stdint.h>
#include <stddef.h>
#include "io_arm64.h"
#include "fb.h"
#include "smp.h"

/* ── Memory map (hardcoded for QEMU virt + -m 512M) ─────────────────────── */
#define RAM_BASE 0x40000000UL
#define RAM_SIZE (512UL * 1024 * 1024)

typedef struct { uint64_t base; uint64_t length; } mmap_entry_t;
static mmap_entry_t boot_mmap[1] = {{ RAM_BASE, RAM_SIZE }};
/* boot_fb is defined (zeroed) in fb.c — no framebuffer on arm64 */

/* ── AArch64 page table (identity map 0..4GiB + ECAM) ───────────────────── */
/*
 * With T0SZ=25 and 4KB granule, TTBR0_EL1 IS the L1 table.
 * L1 index = VA[38:30].  Each entry covers 1GB.
 *
 *   [0]  0x00000000–0x3FFFFFFF  device  (MMIO: PL011, GIC, VirtIO-MMIO)
 *   [1]  0x40000000–0x7FFFFFFF  RAM     (kernel + Python)
 *   [2]  0x80000000–0xBFFFFFFF  RAM
 *   [3]  0xC0000000–0xFFFFFFFF  RAM
 *   [256] 0x4000000000–0x403FFFFFFF  device  (PCIe ECAM config space)
 */
/* Non-static so APs (src/boot/smp_arm64.c) can reuse the same table. */
uint64_t l1_table[512] __attribute__((aligned(4096)));

/* Apply MAIR/TCR/TTBR0 + SCTLR enable. Used by APs that share the L1
 * table populated by the BSP. */
void setup_paging_arm64_ap(void) {
    uint64_t mair = 0x00ULL | (0xFFULL << 8);
    __asm__ volatile("msr mair_el1, %0" :: "r"(mair));

    uint64_t tcr = (25ULL)
                 | (1ULL << 8)
                 | (1ULL << 10)
                 | (3ULL << 12)
                 | (2ULL << 30);
    __asm__ volatile("msr tcr_el1, %0" :: "r"(tcr));
    __asm__ volatile("msr ttbr0_el1, %0" :: "r"((uint64_t)(uintptr_t)l1_table));
    __asm__ volatile("dsb ish");
    __asm__ volatile("isb");

    uint64_t sctlr;
    __asm__ volatile("mrs %0, sctlr_el1" : "=r"(sctlr));
    sctlr |= (1ULL << 0) | (1ULL << 2) | (1ULL << 12);
    __asm__ volatile("msr sctlr_el1, %0\nisb" :: "r"(sctlr));
}

static void setup_paging_arm64(void) {
    /* 1-GiB block descriptors: AF=1, SH=ISH (11), AttrIdx as noted */
#define BLK_DEVICE  ((0ULL<<2)|(1ULL<<10)|(0b01ULL))           /* AttrIdx=0 */
#define BLK_NORMAL  ((1ULL<<2)|(1ULL<<10)|(3ULL<<8)|(0b01ULL)) /* AttrIdx=1 */
    l1_table[0] = 0x00000000ULL | BLK_DEVICE;    /* 0–1 GiB: MMIO */
    l1_table[1] = 0x40000000ULL | BLK_NORMAL;    /* 1–2 GiB: RAM  */
    l1_table[2] = 0x80000000ULL | BLK_NORMAL;
    l1_table[3] = 0xC0000000ULL | BLK_NORMAL;
    /* PCIe ECAM: 0x4010000000 sits in the 256th GB block */
    l1_table[256] = 0x4000000000ULL | BLK_DEVICE;

    setup_paging_arm64_ap();
}

/* ── TLS: set TPIDR_EL0 to a small zeroed region ─────────────────────────── */
static uint8_t _tls_area[128] __attribute__((aligned(16)));
static void tls_init_arm64(void) {
    for (int i = 0; i < 128; i++) _tls_area[i] = 0;
    uintptr_t base = (uintptr_t)&_tls_area[64];
    *(uint64_t *)base = base;   /* self-pointer at TP:0 */
    __asm__ volatile("msr tpidr_el0, %0" :: "r"(base));
    __asm__ volatile("msr tpidrro_el0, %0" :: "r"(base));
}

/* ── PIT counter shim for arm64 ───────────────────────────────────────────── */
/*
 * On arm64 the generic timer drives _pit_ticks via pit_tick() called from
 * interrupt_dispatch_python() in hal.c (same path as x86 PIT).
 * pit_init is a no-op; timer frequency is set in timer_arm64_init().
 */
extern volatile uint64_t _pit_ticks;
void pit_tick(void)              { _pit_ticks++; }
void pit_init(unsigned int hz)   { (void)hz; }

/* ── External declarations ────────────────────────────────────────────────── */
extern void gic_init(void);
extern void timer_arm64_init(void);
extern void python_kernel_start(mmap_entry_t *mmap, int mmap_count,
                                framebuffer_info_t *fb);
/* exception_vectors defined in boot_arm64.S */
extern uint64_t exception_vectors;

void kernel_main_arm64(uint64_t dtb_ptr) {
    (void)dtb_ptr;   /* DTB parsing deferred — hardcode QEMU virt layout */

    pl011_puts("[PythonOS/arm64] boot: serial OK\n");
    setup_paging_arm64();
    pl011_puts("[PythonOS/arm64] boot: MMU enabled\n");
    tls_init_arm64();
    pl011_puts("[PythonOS/arm64] boot: TLS initialized\n");

    /* Install exception vector table */
    __asm__ volatile("msr vbar_el1, %0\nisb" :: "r"((uint64_t)&exception_vectors));
    pl011_puts("[PythonOS/arm64] boot: VBAR set\n");

    /* Bring up GIC and start the generic timer at 100 Hz */
    gic_init();
    pl011_puts("[PythonOS/arm64] boot: GIC initialized\n");
    timer_arm64_init();
    pl011_puts("[PythonOS/arm64] boot: timer started\n");

    /* Unmask IRQs (clear I bit in DAIF) */
    __asm__ volatile("msr daifclr, #2");

    /* Bring up secondary cores via PSCI CPU_ON. With QEMU virt -smp 1
     * (the default in our Makefile) this no-ops; with -smp 2+ it brings
     * each AP into ap_runtime_loop() ready to take pthread workers. */
    pl011_puts("[PythonOS/arm64] boot: about to call smp_init\n");
    smp_init(NULL);
    pl011_puts("[PythonOS/arm64] boot: SMP init complete, online=");
    {
        char buf[8];
        unsigned n = smp_online_count();
        if (n == 0) { buf[0] = '0'; buf[1] = '\n'; buf[2] = 0; }
        else {
            int i = 0;
            char tmp[8];
            int t = 0;
            while (n > 0) { tmp[t++] = '0' + (n % 10); n /= 10; }
            while (t > 0) { buf[i++] = tmp[--t]; }
            buf[i++] = '\n';
            buf[i] = 0;
        }
        pl011_puts(buf);
    }

    pl011_puts("[PythonOS/arm64] boot: starting Python kernel\n");
    python_kernel_start(boot_mmap, 1, &boot_fb);
    pl011_puts("[PythonOS/arm64] FATAL: python_kernel_start returned\n");
    for (;;) __asm__ volatile("wfe");
}
