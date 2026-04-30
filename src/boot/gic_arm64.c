/*
 * gic_arm64.c — GICv2 init, arm64 generic timer, and IRQ dispatch.
 *
 * GICv2 on QEMU virt:
 *   Distributor  0x08000000
 *   CPU interface 0x08010000
 *
 * Timer: EL1 physical timer (CNTP), PPI #14 = GIC ID 30.
 * On every tick, interrupt_dispatch_python(0x20, ...) is called so the
 * Python-side IRQ.TIMER handler fires — same vector as the x86 PIT.
 */

#include <stdint.h>

/* ── GICv2 register layout ─────────────────────────────────────────────────── */

#define GICD_BASE  0x08000000UL
#define GICC_BASE  0x08010000UL

static inline uint32_t gicd_r(uint32_t off) {
    return *(volatile uint32_t *)(GICD_BASE + off);
}
static inline void gicd_w(uint32_t off, uint32_t v) {
    *(volatile uint32_t *)(GICD_BASE + off) = v;
}
static inline uint32_t gicc_r(uint32_t off) {
    return *(volatile uint32_t *)(GICC_BASE + off);
}
static inline void gicc_w(uint32_t off, uint32_t v) {
    *(volatile uint32_t *)(GICC_BASE + off) = v;
}

/* ── GIC init ──────────────────────────────────────────────────────────────── */

/* Per-CPU GICv2 CPU interface init. Called once on the BSP from gic_init
 * and once per AP from ap_entry_arm64_c (src/boot/smp_arm64.c). */
void gic_cpu_iface_init(void) {
    gicc_w(0x004, 0xFF);   /* GICC_PMR: priority mask */
    gicc_w(0x008, 0x07);   /* GICC_BPR: all sub-priority */
    gicc_w(0x000, 1);      /* GICC_CTLR: enable */
}

void gic_init(void) {
    /* Disable distributor while configuring */
    gicd_w(0x000, 0);
    __asm__ volatile("dsb sy");

    /* Number of implemented interrupt lines (SPIs start at 32) */
    uint32_t typer = gicd_r(0x004);
    int n_lines = 32 * ((int)(typer & 0x1F) + 1);

    /* Disable all SPIs; leave SGIs/PPIs (0-31) untouched */
    for (int i = 1; i < n_lines / 32; i++)
        gicd_w(0x180 + i * 4, 0xFFFFFFFF);   /* ICENABLER */

    /* All interrupts: group 0, priority 0xA0, level-sensitive */
    for (int i = 0; i < n_lines / 4; i++)
        gicd_w(0x400 + i * 4, 0xA0A0A0A0);   /* IPRIORITYR */
    for (int i = 8; i < n_lines / 4; i++)
        gicd_w(0x800 + i * 4, 0x01010101);    /* ITARGETSR: CPU 0 */
    for (int i = 0; i < n_lines / 4; i++)
        gicd_w(0x080 + i * 4, 0x00000000);    /* IGROUPR: group 0 */

    /* Enable distributor (group 0) */
    gicd_w(0x000, 1);

    /* Per-CPU CPU interface (BSP). */
    gic_cpu_iface_init();
}

void gic_enable_irq(int irq) {
    gicd_w(0x100 + (irq / 32) * 4, 1u << (irq % 32));  /* ISENABLER */
}

static uint32_t gic_ack(void) {
    return gicc_r(0x00C);   /* GICC_IAR */
}

static void gic_eoi(uint32_t id) {
    gicc_w(0x010, id);      /* GICC_EOIR */
}

/* ── Physical timer (EL1 CNTP, PPI #14 = GIC ID 30) ──────────────────────── */

#define TIMER_IRQ   30
#define TIMER_HZ   100

static uint64_t _timer_interval;

void timer_arm64_init(void) {
    uint64_t freq;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
    _timer_interval = freq / TIMER_HZ;

    __asm__ volatile("msr cntp_tval_el0, %0" :: "r"(_timer_interval));
    __asm__ volatile("msr cntp_ctl_el0,  %0" :: "r"((uint64_t)1));
    __asm__ volatile("isb");

    gic_enable_irq(TIMER_IRQ);
}

static void timer_arm64_reload(void) {
    __asm__ volatile("msr cntp_tval_el0, %0" :: "r"(_timer_interval));
}

/* ── IRQ dispatch bridge ───────────────────────────────────────────────────── */

/* Declared in hal.c; increments _pit_ticks and forwards to Python router. */
extern void interrupt_dispatch_python(uint64_t vector, uint64_t error_code,
                                       uint64_t rip, uint64_t cs,
                                       uint64_t rflags, uint64_t rsp);

/*
 * Called from el1h_irq_handler in boot_arm64.S.
 * Acknowledge the GIC, dispatch to Python, reload the timer, EOI.
 */
void arm64_irq_handler(void) {
    uint32_t id = gic_ack();

    if (id >= 1020) {          /* spurious; 1020–1023 are special */
        if (id != 1023) gic_eoi(id);
        return;
    }

    if (id == TIMER_IRQ) {
        timer_arm64_reload();
        /* vector 0x20 = IRQ.TIMER — matches the Python-side handler */
        interrupt_dispatch_python(0x20, 0, 0, 0, 0, 0);
    } else {
        /* Other IRQs: map SPI n to vector 0x40+n for Python handlers */
        interrupt_dispatch_python(0x40 + id, 0, 0, 0, 0, 0);
    }

    gic_eoi(id);
}
