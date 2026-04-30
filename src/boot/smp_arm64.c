/*
 * smp_arm64.c — SMP bring-up and worker dispatch for AArch64.
 *
 * Mirrors the x86 src/boot/smp.c API (smp_submit_worker / smp_join_worker /
 * smp_worker_done / smp_cpu_count / smp_online_count /
 * smp_worker_selftest_count) so the rest of the kernel — notably
 * src/libc/pthread.c — can use a single set of declarations across archs.
 *
 * Bring-up uses PSCI 0.2 CPU_ON via HVC. Each secondary core enters the
 * assembly stub ap_entry_arm64_asm (in boot_arm64.S) with x0 = the cpu
 * index we passed as PSCI context_id; that stub drops to EL1, sets up the
 * per-AP stack from ap_stack_top[], and tail-calls ap_entry_arm64_c here.
 *
 * No GIC SGI is required for inter-core wakeup: the producer writes the
 * mailbox and issues "dsb sy; sev"; APs spin on mailbox_seq via wfe.
 */

#include <stdint.h>
#include <stddef.h>
#include "smp.h"
#include "spinlock.h"
#include "tls.h"

#define ARM64_MAX_CPUS 8
#define AP_STACK_SIZE_ARM64 (256U * 1024U)
#define PSCI_CPU_ON_AARCH64 0xC4000003UL

typedef struct {
    uint64_t mpidr;
    uint8_t is_bsp;
    volatile uint8_t online;
    volatile uint8_t runtime_ready;
    volatile uint32_t mailbox_seq;
    volatile uint32_t mailbox_done;
    uint64_t (*mailbox_fn)(void *cpu, void *arg);
    void *mailbox_arg;
    volatile uint64_t mailbox_result;
    volatile uint32_t worker_selftests;
    /* Per-AP TLS area. CPython's __thread storage on AArch64 indexes
     * through TPIDR_EL0, so each core that runs interpreter code needs
     * its own area. The BSP keeps using the area in main_arm64.c; APs
     * each get their own slab here. */
    uint8_t tls_area[PYTHONOS_TLS_AREA_SIZE * 2] __attribute__((aligned(16)));
    uint8_t stack[AP_STACK_SIZE_ARM64] __attribute__((aligned(16)));
} smp_cpu_arm64_t;

static smp_cpu_arm64_t cpus[ARM64_MAX_CPUS];
static uint32_t cpu_count;
static volatile uint32_t online_count;
static volatile uint32_t worker_selftest_count;
static spinlock_t smp_worker_lock = SPINLOCK_INITIALIZER;

/* Picked up by the AP entry asm stub to set sp before any C call.
 * Populated by smp_init before each PSCI CPU_ON. */
uint64_t ap_stack_top[ARM64_MAX_CPUS];

/* Defined in boot_arm64.S — the address PSCI hands to secondary cores. */
extern void ap_entry_arm64_asm(void);

/* Defined in main_arm64.c — refactored MMU enable that does NOT
 * reinitialize the shared L1 page table (already populated by BSP). */
extern void setup_paging_arm64_ap(void);

/* Defined in boot_arm64.S — exception vector table, shared across cores. */
extern uint64_t exception_vectors;

/* Defined in gic_arm64.c — per-CPU GICv2 CPU interface init. */
extern void gic_cpu_iface_init(void);

static void smp_worker_selftest_run(void);

static int64_t psci_call(uint64_t fn, uint64_t a1, uint64_t a2, uint64_t a3) {
    register uint64_t x0 __asm__("x0") = fn;
    register uint64_t x1 __asm__("x1") = a1;
    register uint64_t x2 __asm__("x2") = a2;
    register uint64_t x3 __asm__("x3") = a3;
    __asm__ volatile("hvc #0"
                     : "+r"(x0)
                     : "r"(x1), "r"(x2), "r"(x3)
                     : "memory");
    return (int64_t)x0;
}

static uint64_t mpidr_self(void) {
    uint64_t mpidr;
    __asm__ volatile("mrs %0, mpidr_el1" : "=r"(mpidr));
    return mpidr;
}

static void tls_init_for_ap(smp_cpu_arm64_t *cpu) {
    /* Match tls_init_arm64() in main_arm64.c: zero the area, place a
     * self-pointer at the centre, and program TPIDR_EL0 / TPIDRRO_EL0. */
    for (size_t i = 0; i < sizeof cpu->tls_area; i++) {
        cpu->tls_area[i] = 0;
    }
    uintptr_t base = (uintptr_t)&cpu->tls_area[PYTHONOS_TLS_AREA_SIZE];
    *(uint64_t *)base = base;
    __asm__ volatile("msr tpidr_el0, %0" :: "r"(base));
    __asm__ volatile("msr tpidrro_el0, %0" :: "r"(base));
}

static void ap_runtime_loop(smp_cpu_arm64_t *cpu) {
    cpu->online = 1;
    cpu->runtime_ready = 1;
    __sync_synchronize();
    __sync_add_and_fetch(&online_count, 1);

    for (;;) {
        uint32_t seq = cpu->mailbox_seq;
        if (seq != cpu->mailbox_done) {
            uint64_t (*fn)(void *, void *) = cpu->mailbox_fn;
            void *arg = cpu->mailbox_arg;
            uint64_t result = 0;
            if (fn) {
                result = fn((void *)cpu, arg);
            }
            cpu->mailbox_result = result;
            __sync_synchronize();
            cpu->mailbox_done = seq;
            __asm__ volatile("dsb sy");
            __asm__ volatile("sev");
        } else {
            __asm__ volatile("wfe");
        }
    }
}

/* Called from ap_entry_arm64_asm in boot_arm64.S after the EL drop and
 * stack setup. cpu_idx is the index PSCI carried as context_id. */
void ap_entry_arm64_c(uint32_t cpu_idx) {
    if (cpu_idx >= ARM64_MAX_CPUS) {
        for (;;) __asm__ volatile("wfe");
    }
    smp_cpu_arm64_t *cpu = &cpus[cpu_idx];
    cpu->mpidr = mpidr_self();

    setup_paging_arm64_ap();
    __asm__ volatile("msr vbar_el1, %0\nisb"
                     :: "r"((uint64_t)&exception_vectors));
    tls_init_for_ap(cpu);
    gic_cpu_iface_init();
    /* Unmask IRQs (clear I bit in DAIF) so an AP receiving an SGI in
     * future can dispatch normally. The mailbox path itself does not
     * require IRQs — it polls — but per-CPU timer or signal delivery
     * eventually will. */
    __asm__ volatile("msr daifclr, #2");

    ap_runtime_loop(cpu);
}

static int try_psci_cpu_on(uint32_t cpu_idx, uint64_t target_mpidr) {
    ap_stack_top[cpu_idx] =
        (uint64_t)(uintptr_t)&cpus[cpu_idx].stack[AP_STACK_SIZE_ARM64];
    cpus[cpu_idx].mpidr = target_mpidr;
    cpus[cpu_idx].is_bsp = 0;
    cpus[cpu_idx].online = 0;
    cpus[cpu_idx].runtime_ready = 0;
    cpus[cpu_idx].mailbox_seq = 0;
    cpus[cpu_idx].mailbox_done = 0;
    __sync_synchronize();
    int64_t rc = psci_call(PSCI_CPU_ON_AARCH64, target_mpidr,
                           (uint64_t)(uintptr_t)ap_entry_arm64_asm,
                           (uint64_t)cpu_idx);
    return rc == 0;
}

void smp_init(void *mb2_info) {
    (void)mb2_info;  /* arm64 has no Multiboot2; QEMU virt layout is fixed. */

    cpu_count = 0;
    online_count = 0;
    worker_selftest_count = 0;

    /* Register BSP as cpu 0. */
    cpus[0].mpidr = mpidr_self();
    cpus[0].is_bsp = 1;
    cpus[0].online = 1;
    cpus[0].runtime_ready = 1;
    cpu_count = 1;
    online_count = 1;

    /* Probe MPIDR Aff0 = 1..ARM64_MAX_CPUS-1. QEMU virt with -smp N
     * exposes cores at sequential Aff0 values. PSCI returns 0 on
     * success and a negative error otherwise; once we hit a missing
     * core we stop probing.
     *
     * PSCI target_cpu only encodes Aff0..Aff3 (bits 7:0, 15:8, 23:16,
     * 39:32). The RES1 bit (31), U bit (30), and MT bit (24) of
     * MPIDR_EL1 must be 0 in target_cpu — passing them through trips
     * NOT_SUPPORTED on QEMU. We therefore preserve only the affinity
     * fields from the BSP's MPIDR; for our single-cluster layout
     * that's all-zero plus the new Aff0. */
    uint64_t base_mpidr = cpus[0].mpidr &
                          (0xFFULL << 32 |  /* Aff3 */
                           0xFFULL << 16 |  /* Aff2 */
                           0xFFULL << 8);   /* Aff1 */
    for (uint32_t i = 1; i < ARM64_MAX_CPUS; i++) {
        uint64_t target = base_mpidr | (uint64_t)i;
        if (!try_psci_cpu_on(i, target)) {
            break;
        }
        cpu_count++;
        /* Wait for the AP to reach runtime_ready, with a generous bound. */
        for (uint32_t spin = 0; spin < 50000000U; spin++) {
            if (cpus[i].runtime_ready) {
                break;
            }
            __asm__ volatile("yield");
        }
    }

    /* Run a one-shot worker self-test on every online AP, mirroring x86. */
    smp_worker_selftest_run();
}

void smp_bsp_early_init(void) {
    /* No equivalent of the x86 GS-base / FX-save bring-up needed here. */
}

uint32_t smp_cpu_count(void) { return cpu_count; }
uint32_t smp_online_count(void) { return online_count; }
uint32_t smp_worker_selftest_count(void) { return worker_selftest_count; }
uint8_t smp_bsp_apic_id(void) { return 0; }
void smp_lapic_eoi(void) { /* x86-only concept; no-op on arm64. */ }

static uint64_t smp_make_handle(uint32_t index, uint32_t seq) {
    return (((uint64_t)index) << 32) | seq;
}

static int smp_handle_parts(uint64_t handle, uint32_t *idx, uint32_t *seq) {
    uint32_t i = (uint32_t)(handle >> 32);
    uint32_t s = (uint32_t)handle;
    if (i >= cpu_count || s == 0) {
        return 0;
    }
    *idx = i;
    *seq = s;
    return 1;
}

int smp_submit_worker(smp_worker_fn_t fn, void *arg, uint64_t *handle) {
    if (!fn || !handle) {
        return 0;
    }
    spin_lock(&smp_worker_lock);
    for (uint32_t i = 0; i < cpu_count; i++) {
        smp_cpu_arm64_t *cpu = &cpus[i];
        if (cpu->is_bsp || !cpu->online || !cpu->runtime_ready) {
            continue;
        }
        if (cpu->mailbox_seq != cpu->mailbox_done) {
            continue;
        }
        uint32_t seq = cpu->mailbox_seq + 1;
        if (seq == 0) {
            seq = 1;
        }
        cpu->mailbox_fn = fn;
        cpu->mailbox_arg = arg;
        __sync_synchronize();
        cpu->mailbox_seq = seq;
        __asm__ volatile("dsb sy");
        __asm__ volatile("sev");
        *handle = smp_make_handle(i, seq);
        spin_unlock(&smp_worker_lock);
        return 1;
    }
    spin_unlock(&smp_worker_lock);
    return 0;
}

int smp_worker_done(uint64_t handle) {
    uint32_t idx, seq;
    if (!smp_handle_parts(handle, &idx, &seq)) {
        return 0;
    }
    return cpus[idx].mailbox_done == seq;
}

uint64_t smp_worker_result(uint64_t handle) {
    uint32_t idx, seq;
    if (!smp_handle_parts(handle, &idx, &seq)) {
        return 0;
    }
    if (cpus[idx].mailbox_done != seq) {
        return 0;
    }
    return cpus[idx].mailbox_result;
}

int smp_join_worker(uint64_t handle, uint64_t *result) {
    uint32_t idx, seq;
    if (!smp_handle_parts(handle, &idx, &seq)) {
        return 0;
    }
    while (cpus[idx].mailbox_done != seq) {
        __asm__ volatile("wfe");
    }
    if (result) {
        *result = cpus[idx].mailbox_result;
    }
    return 1;
}

/* ── Worker self-test (analogue of x86 smp_run_worker_selftest) ──────── */

static uint64_t smp_worker_selftest_job(void *cpu_arg, void *arg) {
    (void)arg;
    smp_cpu_arm64_t *cpu = (smp_cpu_arm64_t *)cpu_arg;
    cpu->worker_selftests++;
    return __sync_add_and_fetch(&worker_selftest_count, 1);
}

static void smp_worker_selftest_run(void) {
    worker_selftest_count = 0;
    __sync_synchronize();
    /* Submit one job to every non-BSP online CPU and wait for completion.
     * BSP counts itself for parity with x86 (smp_worker_selftest_count
     * reports total participants). */
    for (uint32_t i = 0; i < cpu_count; i++) {
        if (cpus[i].is_bsp) {
            cpus[i].worker_selftests++;
            __sync_add_and_fetch(&worker_selftest_count, 1);
            continue;
        }
        if (!cpus[i].online || !cpus[i].runtime_ready) {
            continue;
        }
        uint64_t handle = 0;
        if (smp_submit_worker(smp_worker_selftest_job, NULL, &handle)) {
            (void)smp_join_worker(handle, NULL);
        }
    }
}
