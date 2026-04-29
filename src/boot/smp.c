#include <stdint.h>
#include <stddef.h>
#include "gdt.h"
#include "idt.h"
#include "io.h"
#include "spinlock.h"
#include "smp.h"
#include "tls.h"

#define SMP_MAX_CPUS 8
#define AP_STACK_SIZE (256U * 1024U)
#define AP_TRAMPOLINE_ADDR 0x8000UL
#define AP_TRAMPOLINE_VECTOR (AP_TRAMPOLINE_ADDR >> 12)

#define IA32_APIC_BASE 0x1B
#define IA32_GS_BASE 0xC0000101U
#define APIC_BASE_ENABLE (1ULL << 11)

#define LAPIC_ID   0x020
#define LAPIC_EOI  0x0B0
#define LAPIC_SVR  0x0F0
#define LAPIC_ESR  0x280
#define LAPIC_ICR_LOW  0x300
#define LAPIC_ICR_HIGH 0x310
#define LAPIC_MAILBOX_VECTOR 0xFE

#define ICR_DELIVERY_STATUS (1U << 12)
#define ICR_DELIVERY_FIXED  (0U << 8)
#define ICR_DELIVERY_INIT   (5U << 8)
#define ICR_DELIVERY_SIPI   (6U << 8)
#define ICR_LEVEL_ASSERT    (1U << 14)
#define ICR_TRIGGER_LEVEL   (1U << 15)

#define TRAMP_MAGIC_PML4  0x50594f534d503031ULL
#define TRAMP_MAGIC_STACK 0x50594f534d503032ULL
#define TRAMP_MAGIC_ENTRY 0x50594f534d503033ULL
#define TRAMP_MAGIC_CPU   0x50594f534d503034ULL

typedef struct {
    uint32_t total_size;
    uint32_t reserved;
} mb2_info_t;

typedef struct {
    uint32_t type;
    uint32_t size;
} mb2_tag_t;

typedef struct {
    char signature[8];
    uint8_t checksum;
    char oemid[6];
    uint8_t revision;
    uint32_t rsdt_address;
    uint32_t length;
    uint64_t xsdt_address;
    uint8_t extended_checksum;
    uint8_t reserved[3];
} __attribute__((packed)) rsdp_t;

typedef struct {
    char signature[4];
    uint32_t length;
    uint8_t revision;
    uint8_t checksum;
    char oemid[6];
    char oem_table_id[8];
    uint32_t oem_revision;
    uint32_t creator_id;
    uint32_t creator_revision;
} __attribute__((packed)) acpi_sdt_header_t;

typedef struct {
    acpi_sdt_header_t header;
    uint32_t local_apic_address;
    uint32_t flags;
    uint8_t entries[];
} __attribute__((packed)) madt_t;

typedef struct {
    uint8_t type;
    uint8_t length;
} __attribute__((packed)) madt_entry_t;

typedef struct {
    uint8_t type;
    uint8_t length;
    uint8_t acpi_processor_id;
    uint8_t apic_id;
    uint32_t flags;
} __attribute__((packed)) madt_lapic_t;

typedef struct {
    uint8_t type;
    uint8_t length;
    uint16_t reserved;
    uint64_t local_apic_address;
} __attribute__((packed)) madt_lapic_override_t;

typedef struct {
    uint8_t fxsave_area[512] __attribute__((aligned(16)));
    uint8_t apic_id;
    uint8_t acpi_processor_id;
    uint8_t is_bsp;
    volatile uint8_t online;
    volatile uint8_t runtime_ready;
    volatile uint32_t mailbox_seq;
    volatile uint32_t mailbox_done;
    uint64_t (*mailbox_fn)(void *, void *);
    void *mailbox_arg;
    volatile uint64_t mailbox_result;
    volatile uint32_t worker_selftests;
    uint8_t tls_area[PYTHONOS_TLS_AREA_SIZE] __attribute__((aligned(16)));
    uint8_t stack[AP_STACK_SIZE] __attribute__((aligned(16)));
} smp_cpu_t;

_Static_assert(offsetof(smp_cpu_t, fxsave_area) == 0,
               "isr_stubs.asm expects smp_cpu_t.fxsave_area at GS:0");

extern const uint8_t ap_trampoline_start[];
extern const uint8_t ap_trampoline_end[];

static smp_cpu_t cpus[SMP_MAX_CPUS];
static uint32_t cpu_count;
static volatile uint32_t online_count;
static volatile uint32_t worker_selftest_count;
static uint8_t bsp_apic_id_value;
static uintptr_t lapic_base;
static int lapic_enabled;

static volatile uint64_t *tramp_pml4_slot;
static volatile uint64_t *tramp_stack_slot;
static volatile uint64_t *tramp_entry_slot;
static volatile uint64_t *tramp_cpu_slot;
static spinlock_t smp_worker_lock = SPINLOCK_INITIALIZER;

void smp_ap_entry(smp_cpu_t *cpu);

static int memeq(const void *a, const char *b, size_t n) {
    const uint8_t *pa = (const uint8_t *)a;
    const uint8_t *pb = (const uint8_t *)b;
    for (size_t i = 0; i < n; i++) {
        if (pa[i] != pb[i]) {
            return 0;
        }
    }
    return 1;
}

static uint8_t checksum8(const void *ptr, size_t len) {
    const uint8_t *p = (const uint8_t *)ptr;
    uint8_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum = (uint8_t)(sum + p[i]);
    }
    return sum;
}

static int acpi_table_ok(const acpi_sdt_header_t *h, const char *sig) {
    if (!h || !memeq(h->signature, sig, 4)) {
        return 0;
    }
    if (h->length < sizeof(acpi_sdt_header_t)) {
        return 0;
    }
    return checksum8(h, h->length) == 0;
}

static const rsdp_t *rsdp_from_mb2(void *mb2_info) {
    if (!mb2_info) {
        return NULL;
    }

    mb2_info_t *mb2 = (mb2_info_t *)mb2_info;
    uint8_t *ptr = (uint8_t *)mb2 + 8;
    uint8_t *end = (uint8_t *)mb2 + mb2->total_size;

    while (ptr + sizeof(mb2_tag_t) <= end) {
        mb2_tag_t *tag = (mb2_tag_t *)ptr;
        if (tag->type == 0) {
            break;
        }
        if ((tag->type == 14 || tag->type == 15) && tag->size >= sizeof(mb2_tag_t) + 20) {
            const rsdp_t *rsdp = (const rsdp_t *)(ptr + sizeof(mb2_tag_t));
            if (memeq(rsdp->signature, "RSD PTR ", 8) && checksum8(rsdp, 20) == 0) {
                return rsdp;
            }
        }
        ptr += (tag->size + 7) & ~7U;
    }

    return NULL;
}

static const rsdp_t *rsdp_scan_range(uintptr_t start, uintptr_t end) {
    for (uintptr_t addr = start; addr + 20 <= end; addr += 16) {
        const rsdp_t *rsdp = (const rsdp_t *)addr;
        if (memeq(rsdp->signature, "RSD PTR ", 8) && checksum8(rsdp, 20) == 0) {
            return rsdp;
        }
    }
    return NULL;
}

static uint16_t read_phys16(uintptr_t addr) {
    uint16_t value;
    __asm__ volatile("movw (%1), %0" : "=r"(value) : "r"(addr) : "memory");
    return value;
}

static const rsdp_t *find_rsdp(void *mb2_info) {
    const rsdp_t *rsdp = rsdp_from_mb2(mb2_info);
    if (rsdp) {
        return rsdp;
    }

    uint16_t ebda_segment = read_phys16(0x40E);
    uintptr_t ebda = ((uintptr_t)ebda_segment) << 4;
    if (ebda >= 0x80000 && ebda < 0xA0000) {
        rsdp = rsdp_scan_range(ebda, ebda + 1024);
        if (rsdp) {
            return rsdp;
        }
    }

    return rsdp_scan_range(0xE0000, 0x100000);
}

static const acpi_sdt_header_t *find_table_rsdt(uint32_t rsdt_addr, const char *sig) {
    const acpi_sdt_header_t *rsdt = (const acpi_sdt_header_t *)(uintptr_t)rsdt_addr;
    if (!acpi_table_ok(rsdt, "RSDT")) {
        return NULL;
    }

    uint32_t entries = (rsdt->length - sizeof(*rsdt)) / 4;
    const uint32_t *table = (const uint32_t *)((const uint8_t *)rsdt + sizeof(*rsdt));
    for (uint32_t i = 0; i < entries; i++) {
        const acpi_sdt_header_t *h = (const acpi_sdt_header_t *)(uintptr_t)table[i];
        if (acpi_table_ok(h, sig)) {
            return h;
        }
    }
    return NULL;
}

static const acpi_sdt_header_t *find_table_xsdt(uint64_t xsdt_addr, const char *sig) {
    const acpi_sdt_header_t *xsdt = (const acpi_sdt_header_t *)(uintptr_t)xsdt_addr;
    if (!acpi_table_ok(xsdt, "XSDT")) {
        return NULL;
    }

    uint32_t entries = (xsdt->length - sizeof(*xsdt)) / 8;
    const uint64_t *table = (const uint64_t *)((const uint8_t *)xsdt + sizeof(*xsdt));
    for (uint32_t i = 0; i < entries; i++) {
        const acpi_sdt_header_t *h = (const acpi_sdt_header_t *)(uintptr_t)table[i];
        if (acpi_table_ok(h, sig)) {
            return h;
        }
    }
    return NULL;
}

static const acpi_sdt_header_t *find_acpi_table(const rsdp_t *rsdp, const char *sig) {
    if (!rsdp) {
        return NULL;
    }

    if (rsdp->revision >= 2 && rsdp->length >= sizeof(rsdp_t) &&
        checksum8(rsdp, rsdp->length) == 0 && rsdp->xsdt_address) {
        const acpi_sdt_header_t *h = find_table_xsdt(rsdp->xsdt_address, sig);
        if (h) {
            return h;
        }
    }

    if (rsdp->rsdt_address) {
        return find_table_rsdt(rsdp->rsdt_address, sig);
    }
    return NULL;
}

static void add_cpu(uint8_t apic_id, uint8_t acpi_processor_id) {
    for (uint32_t i = 0; i < cpu_count; i++) {
        if (cpus[i].apic_id == apic_id) {
            return;
        }
    }
    if (cpu_count >= SMP_MAX_CPUS) {
        return;
    }

    cpus[cpu_count].apic_id = apic_id;
    cpus[cpu_count].acpi_processor_id = acpi_processor_id;
    cpus[cpu_count].is_bsp = 0;
    cpus[cpu_count].online = 0;
    cpus[cpu_count].runtime_ready = 0;
    cpus[cpu_count].mailbox_seq = 0;
    cpus[cpu_count].mailbox_done = 0;
    cpus[cpu_count].mailbox_fn = NULL;
    cpus[cpu_count].mailbox_arg = NULL;
    cpus[cpu_count].mailbox_result = 0;
    cpus[cpu_count].worker_selftests = 0;
    cpu_count++;
}

static void discover_cpus(void *mb2_info) {
    const rsdp_t *rsdp = find_rsdp(mb2_info);
    const madt_t *madt = (const madt_t *)find_acpi_table(rsdp, "APIC");
    if (!madt) {
        return;
    }

    lapic_base = madt->local_apic_address;

    const uint8_t *ptr = madt->entries;
    const uint8_t *end = (const uint8_t *)madt + madt->header.length;
    while (ptr + sizeof(madt_entry_t) <= end) {
        const madt_entry_t *entry = (const madt_entry_t *)ptr;
        if (entry->length < sizeof(madt_entry_t) || ptr + entry->length > end) {
            break;
        }

        if (entry->type == 0 && entry->length >= sizeof(madt_lapic_t)) {
            const madt_lapic_t *lapic = (const madt_lapic_t *)entry;
            if (lapic->flags & 0x3U) {
                add_cpu(lapic->apic_id, lapic->acpi_processor_id);
            }
        } else if (entry->type == 5 && entry->length >= sizeof(madt_lapic_override_t)) {
            const madt_lapic_override_t *override = (const madt_lapic_override_t *)entry;
            lapic_base = (uintptr_t)override->local_apic_address;
        }

        ptr += entry->length;
    }
}

static void cpuid_leaf(uint32_t leaf, uint32_t *a, uint32_t *b, uint32_t *c, uint32_t *d) {
    __asm__ volatile("cpuid"
                     : "=a"(*a), "=b"(*b), "=c"(*c), "=d"(*d)
                     : "a"(leaf), "c"(0));
}

static uint64_t rdmsr(uint32_t msr) {
    uint32_t lo, hi;
    __asm__ volatile("rdmsr" : "=a"(lo), "=d"(hi) : "c"(msr));
    return ((uint64_t)hi << 32) | lo;
}

static void wrmsr(uint32_t msr, uint64_t value) {
    __asm__ volatile("wrmsr"
                     :
                     : "c"(msr), "a"((uint32_t)value), "d"((uint32_t)(value >> 32))
                     : "memory");
}

static void cpu_set_gs(smp_cpu_t *cpu) {
    wrmsr(IA32_GS_BASE, (uint64_t)(uintptr_t)cpu);
}

static void cpu_tls_init(smp_cpu_t *cpu) {
    if (!tls_init_area(cpu->tls_area, sizeof(cpu->tls_area))) {
        for (;;) {
            __asm__ volatile("cli; hlt");
        }
    }
}

static void cpu_fpu_init(void) {
    uint64_t cr0, cr4;

    __asm__ volatile("mov %%cr0, %0" : "=r"(cr0));
    cr0 &= ~(1UL << 2);
    cr0 |=  (1UL << 1);
    cr0 &= ~(1UL << 3);
    __asm__ volatile("mov %0, %%cr0" :: "r"(cr0) : "memory");

    __asm__ volatile("mov %%cr4, %0" : "=r"(cr4));
    cr4 |= (1UL << 9);
    cr4 |= (1UL << 10);
    __asm__ volatile("mov %0, %%cr4" :: "r"(cr4) : "memory");

    __asm__ volatile("finit");

    uint32_t mxcsr = 0x1F80;
    __asm__ volatile("ldmxcsr %0" :: "m"(mxcsr) : "memory");
}

static uint8_t cpuid_apic_id(void) {
    uint32_t a, b, c, d;
    cpuid_leaf(1, &a, &b, &c, &d);
    return (uint8_t)(b >> 24);
}

static int cpu_has_apic(void) {
    uint32_t a, b, c, d;
    cpuid_leaf(1, &a, &b, &c, &d);
    return (d & (1U << 9)) != 0;
}

static uint32_t lapic_read(uint32_t reg) {
    return mmio_read32(lapic_base + reg);
}

static void lapic_write(uint32_t reg, uint32_t value) {
    mmio_write32(lapic_base + reg, value);
    (void)lapic_read(LAPIC_ID);
}

static void io_delay(void) {
    outb(0x80, 0);
}

static void delay_io(uint32_t count) {
    for (uint32_t i = 0; i < count; i++) {
        io_delay();
    }
}

static void lapic_wait_delivery(void) {
    for (uint32_t i = 0; i < 1000000; i++) {
        if ((lapic_read(LAPIC_ICR_LOW) & ICR_DELIVERY_STATUS) == 0) {
            return;
        }
    }
}

static void lapic_send_ipi(uint8_t apic_id, uint32_t icr_low) {
    lapic_write(LAPIC_ICR_HIGH, ((uint32_t)apic_id) << 24);
    lapic_write(LAPIC_ICR_LOW, icr_low);
    lapic_wait_delivery();
}

static void lapic_enable(void) {
    if (!cpu_has_apic()) {
        return;
    }

    uint64_t base_msr = rdmsr(IA32_APIC_BASE);
    if (!lapic_base) {
        lapic_base = (uintptr_t)(base_msr & 0xFFFFF000ULL);
    }
    base_msr &= ~0xFFFFF000ULL;
    base_msr |= (uint64_t)(lapic_base & 0xFFFFF000ULL);
    base_msr |= APIC_BASE_ENABLE;
    wrmsr(IA32_APIC_BASE, base_msr);

    lapic_write(LAPIC_SVR, lapic_read(LAPIC_SVR) | 0x100U | 0xFFU);
    lapic_write(LAPIC_ESR, 0);
    lapic_enabled = 1;
}

void smp_bsp_early_init(void) {
    cpu_count = 1;
    online_count = 1;
    worker_selftest_count = 0;
    cpus[0].apic_id = cpuid_apic_id();
    cpus[0].acpi_processor_id = 0;
    cpus[0].is_bsp = 1;
    cpus[0].online = 1;
    cpus[0].runtime_ready = 1;
    cpus[0].mailbox_seq = 0;
    cpus[0].mailbox_done = 0;
    cpus[0].mailbox_fn = NULL;
    cpus[0].mailbox_arg = NULL;
    cpus[0].mailbox_result = 0;
    cpus[0].worker_selftests = 0;
    bsp_apic_id_value = cpus[0].apic_id;
    cpu_set_gs(&cpus[0]);
}

static volatile uint64_t *find_trampoline_slot(uint64_t magic) {
    uint8_t *start = (uint8_t *)AP_TRAMPOLINE_ADDR;
    for (uint32_t off = 0; off + sizeof(uint64_t) <= 4096; off += 8) {
        volatile uint64_t *slot = (volatile uint64_t *)(start + off);
        if (*slot == magic) {
            return slot;
        }
    }
    return NULL;
}

static int prepare_trampoline(void) {
    size_t size = (size_t)(ap_trampoline_end - ap_trampoline_start);
    if (size == 0 || size > 4096) {
        return 0;
    }

    uint8_t *dst = (uint8_t *)AP_TRAMPOLINE_ADDR;
    for (size_t i = 0; i < size; i++) {
        dst[i] = ap_trampoline_start[i];
    }
    for (size_t i = size; i < 4096; i++) {
        dst[i] = 0;
    }

    tramp_pml4_slot = find_trampoline_slot(TRAMP_MAGIC_PML4);
    tramp_stack_slot = find_trampoline_slot(TRAMP_MAGIC_STACK);
    tramp_entry_slot = find_trampoline_slot(TRAMP_MAGIC_ENTRY);
    tramp_cpu_slot = find_trampoline_slot(TRAMP_MAGIC_CPU);
    if (!tramp_pml4_slot || !tramp_stack_slot || !tramp_entry_slot || !tramp_cpu_slot) {
        return 0;
    }

    *tramp_pml4_slot = read_cr3();
    *tramp_entry_slot = (uint64_t)(uintptr_t)smp_ap_entry;
    return 1;
}

static void smp_ap_idle_loop(smp_cpu_t *cpu) {
    for (;;) {
        uint32_t seq = cpu->mailbox_seq;
        if (seq != cpu->mailbox_done) {
            __asm__ volatile("cli" ::: "memory");
            uint64_t (*fn)(void *, void *) = cpu->mailbox_fn;
            void *arg = cpu->mailbox_arg;
            __asm__ volatile("sti" ::: "memory");

            uint64_t result = 0;
            if (fn) {
                result = fn(cpu, arg);
            }

            __asm__ volatile("cli" ::: "memory");
            cpu->mailbox_result = result;
            __sync_synchronize();
            cpu->mailbox_done = seq;
            __asm__ volatile("sti" ::: "memory");
            continue;
        }

        __asm__ volatile("sti; hlt" ::: "memory");
    }
}

void smp_ap_entry(smp_cpu_t *cpu) {
    if (!cpu) {
        for (;;) {
            __asm__ volatile("cli; hlt");
        }
    }

    gdt_load();
    cpu_set_gs(cpu);
    idt_load();
    cpu_tls_init(cpu);
    cpu_fpu_init();
    lapic_enable();

    cpu->runtime_ready = 1;
    __sync_synchronize();
    cpu->online = 1;
    __sync_fetch_and_add(&online_count, 1);

    smp_ap_idle_loop(cpu);
}

static int start_ap(smp_cpu_t *cpu) {
    uintptr_t stack_top = (uintptr_t)cpu->stack + AP_STACK_SIZE;
    cpu->online = 0;
    *tramp_stack_slot = stack_top;
    *tramp_cpu_slot = (uint64_t)(uintptr_t)cpu;
    __asm__ volatile("mfence" ::: "memory");

    lapic_send_ipi(cpu->apic_id, ICR_DELIVERY_INIT | ICR_LEVEL_ASSERT | ICR_TRIGGER_LEVEL);
    delay_io(10000);
    lapic_send_ipi(cpu->apic_id, ICR_DELIVERY_INIT | ICR_TRIGGER_LEVEL);
    delay_io(20000);

    for (int sipi = 0; sipi < 2 && !cpu->online; sipi++) {
        lapic_send_ipi(cpu->apic_id, ICR_DELIVERY_SIPI | AP_TRAMPOLINE_VECTOR);
        for (uint32_t wait = 0; wait < 5000000; wait++) {
            if (cpu->online && cpu->runtime_ready) {
                return 1;
            }
            __asm__ volatile("pause");
        }
    }

    return cpu->online != 0 && cpu->runtime_ready != 0;
}

static uint64_t smp_worker_selftest_job(void *cpu_arg, void *arg) {
    (void)arg;
    smp_cpu_t *cpu = (smp_cpu_t *)cpu_arg;
    cpu->worker_selftests++;
    return __sync_add_and_fetch(&worker_selftest_count, 1);
}

static int smp_call_cpu(smp_cpu_t *cpu, uint64_t (*fn)(void *, void *), void *arg) {
    if (!cpu || !cpu->online || !cpu->runtime_ready || !fn) {
        return 0;
    }

    if (cpu->is_bsp) {
        cpu->mailbox_result = fn(cpu, arg);
        return 1;
    }

    uint32_t seq = cpu->mailbox_seq + 1;
    if (seq == 0) {
        seq = 1;
    }
    cpu->mailbox_fn = fn;
    cpu->mailbox_arg = arg;
    __sync_synchronize();
    cpu->mailbox_seq = seq;

    lapic_send_ipi(cpu->apic_id, ICR_DELIVERY_FIXED | LAPIC_MAILBOX_VECTOR);

    for (uint32_t wait = 0; wait < 5000000; wait++) {
        if (cpu->mailbox_done == seq) {
            return 1;
        }
        __asm__ volatile("pause");
    }
    return 0;
}

static uint64_t smp_make_handle(uint32_t index, uint32_t seq) {
    return (((uint64_t)index) << 32) | seq;
}

static int smp_handle_parts(uint64_t handle, uint32_t *index, uint32_t *seq) {
    uint32_t i = (uint32_t)(handle >> 32);
    uint32_t s = (uint32_t)handle;
    if (i >= cpu_count || s == 0) {
        return 0;
    }
    *index = i;
    *seq = s;
    return 1;
}

int smp_submit_worker(smp_worker_fn_t fn, void *arg, uint64_t *handle) {
    if (!fn || !handle || !lapic_enabled) {
        return 0;
    }

    spin_lock(&smp_worker_lock);
    for (uint32_t i = 0; i < cpu_count; i++) {
        smp_cpu_t *cpu = &cpus[i];
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
        *handle = smp_make_handle(i, seq);
        lapic_send_ipi(cpu->apic_id, ICR_DELIVERY_FIXED | LAPIC_MAILBOX_VECTOR);
        spin_unlock(&smp_worker_lock);
        return 1;
    }
    spin_unlock(&smp_worker_lock);
    return 0;
}

int smp_worker_done(uint64_t handle) {
    uint32_t index, seq;
    if (!smp_handle_parts(handle, &index, &seq)) {
        return 0;
    }
    return cpus[index].mailbox_done == seq;
}

uint64_t smp_worker_result(uint64_t handle) {
    uint32_t index, seq;
    if (!smp_handle_parts(handle, &index, &seq)) {
        return 0;
    }
    if (cpus[index].mailbox_done != seq) {
        return 0;
    }
    return cpus[index].mailbox_result;
}

int smp_join_worker(uint64_t handle, uint64_t *result) {
    uint32_t index, seq;
    if (!smp_handle_parts(handle, &index, &seq)) {
        return 0;
    }
    while (cpus[index].mailbox_done != seq) {
        __asm__ volatile("pause");
    }
    if (result) {
        *result = cpus[index].mailbox_result;
    }
    return 1;
}

static void smp_run_worker_selftest(void) {
    worker_selftest_count = 0;
    __sync_synchronize();
    for (uint32_t i = 0; i < cpu_count; i++) {
        if (cpus[i].online && cpus[i].runtime_ready) {
            (void)smp_call_cpu(&cpus[i], smp_worker_selftest_job, NULL);
        }
    }
}

void smp_init(void *mb2_info) {
    cpu_count = 0;
    online_count = 0;
    worker_selftest_count = 0;
    lapic_enabled = 0;
    lapic_base = 0;

    bsp_apic_id_value = cpuid_apic_id();
    discover_cpus(mb2_info);
    if (cpu_count == 0) {
        add_cpu(bsp_apic_id_value, 0);
    }

    int bsp_seen = 0;
    smp_cpu_t *bsp_cpu = &cpus[0];
    for (uint32_t i = 0; i < cpu_count; i++) {
        if (cpus[i].apic_id == bsp_apic_id_value) {
            cpus[i].is_bsp = 1;
            cpus[i].online = 1;
            cpus[i].runtime_ready = 1;
            bsp_cpu = &cpus[i];
            bsp_seen = 1;
            break;
        }
    }
    if (!bsp_seen && cpu_count < SMP_MAX_CPUS) {
        add_cpu(bsp_apic_id_value, 0);
        cpus[cpu_count - 1].is_bsp = 1;
        cpus[cpu_count - 1].online = 1;
        cpus[cpu_count - 1].runtime_ready = 1;
        bsp_cpu = &cpus[cpu_count - 1];
    }
    online_count = 1;
    cpu_set_gs(bsp_cpu);

    lapic_enable();
    if (!lapic_enabled || !prepare_trampoline()) {
        smp_run_worker_selftest();
        return;
    }

    for (uint32_t i = 0; i < cpu_count; i++) {
        if (!cpus[i].is_bsp) {
            (void)start_ap(&cpus[i]);
        }
    }

    smp_run_worker_selftest();
}

uint32_t smp_cpu_count(void) {
    return cpu_count;
}

uint32_t smp_online_count(void) {
    return online_count;
}

uint32_t smp_worker_selftest_count(void) {
    return worker_selftest_count;
}

uint8_t smp_bsp_apic_id(void) {
    return bsp_apic_id_value;
}

void smp_lapic_eoi(void) {
    if (lapic_enabled) {
        lapic_write(LAPIC_EOI, 0);
    }
}
