/*
 * hal.c — Hardware Abstraction Layer Python C extension module
 *
 * Exposes privileged hardware operations to the Python kernel:
 *   - Port I/O (inb/inw/inl/outb/outw/outl)
 *   - Control register access (CR2, CR3)
 *   - MMIO read/write
 *   - Interrupt dispatch bridge (C -> Python)
 *
 * Compiled as a built-in extension module (_hal) and initialized
 * before Py_Initialize() via PyImport_AppendInittab().
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <pthread.h>
#ifndef ARCH_ARM64
#include "../boot/io.h"
#endif
#include "../boot/smp.h"

// Python C API callbacks have fixed signatures; many do not use self/args.
#if defined(__GNUC__)
#pragma GCC diagnostic ignored "-Wunused-parameter"
#endif

// ── Port I/O ────────────────────────────────────────────────────────────────

#ifndef ARCH_ARM64
static PyObject *py_inb(PyObject *self, PyObject *args) {
    unsigned int port;
    if (!PyArg_ParseTuple(args, "I", &port)) return NULL;
    return PyLong_FromUnsignedLong(inb((uint16_t)port));
}

static PyObject *py_inw(PyObject *self, PyObject *args) {
    unsigned int port;
    if (!PyArg_ParseTuple(args, "I", &port)) return NULL;
    return PyLong_FromUnsignedLong(inw((uint16_t)port));
}

static PyObject *py_inl(PyObject *self, PyObject *args) {
    unsigned int port;
    if (!PyArg_ParseTuple(args, "I", &port)) return NULL;
    return PyLong_FromUnsignedLong(inl((uint16_t)port));
}

static PyObject *py_outb(PyObject *self, PyObject *args) {
    unsigned int port, val;
    if (!PyArg_ParseTuple(args, "II", &port, &val)) return NULL;
    outb((uint16_t)port, (uint8_t)val);
    Py_RETURN_NONE;
}

static PyObject *py_outw(PyObject *self, PyObject *args) {
    unsigned int port, val;
    if (!PyArg_ParseTuple(args, "II", &port, &val)) return NULL;
    outw((uint16_t)port, (uint16_t)val);
    Py_RETURN_NONE;
}

static PyObject *py_outl(PyObject *self, PyObject *args) {
    unsigned int port, val;
    if (!PyArg_ParseTuple(args, "II", &port, &val)) return NULL;
    outl((uint16_t)port, (uint32_t)val);
    Py_RETURN_NONE;
}
#endif /* !ARCH_ARM64 */

// ── Control registers ────────────────────────────────────────────────────────

#ifndef ARCH_ARM64
static PyObject *py_read_cr2(PyObject *self, PyObject *args) {
    return PyLong_FromUnsignedLongLong(read_cr2());
}

static PyObject *py_read_cr3(PyObject *self, PyObject *args) {
    return PyLong_FromUnsignedLongLong(read_cr3());
}

static PyObject *py_write_cr3(PyObject *self, PyObject *args) {
    unsigned long long val;
    if (!PyArg_ParseTuple(args, "K", &val)) return NULL;
    write_cr3((uint64_t)val);
    Py_RETURN_NONE;
}
#endif /* !ARCH_ARM64 */

// ── arm64 MMIO-based port I/O and control register equivalents ───────────────

#ifdef ARCH_ARM64
static PyObject *py_inb_arm64(PyObject *self, PyObject *args) {
    unsigned long long addr;
    if (!PyArg_ParseTuple(args, "K", &addr)) return NULL;
    return PyLong_FromUnsignedLong(*(volatile uint8_t *)(uintptr_t)addr);
}
static PyObject *py_outb_arm64(PyObject *self, PyObject *args) {
    unsigned long long addr; unsigned int val;
    if (!PyArg_ParseTuple(args, "KI", &addr, &val)) return NULL;
    *(volatile uint8_t *)(uintptr_t)addr = (uint8_t)val;
    Py_RETURN_NONE;
}
/* read_cr2 → FAR_EL1 (fault address) */
static PyObject *py_read_cr2_arm64(PyObject *self, PyObject *args) {
    uint64_t far;
    __asm__ volatile("mrs %0, far_el1" : "=r"(far));
    return PyLong_FromUnsignedLongLong(far);
}
/* read_cr3 → TTBR0_EL1 */
static PyObject *py_read_cr3_arm64(PyObject *self, PyObject *args) {
    uint64_t ttbr;
    __asm__ volatile("mrs %0, ttbr0_el1" : "=r"(ttbr));
    return PyLong_FromUnsignedLongLong(ttbr);
}
/* write_cr3 → TTBR0_EL1 */
static PyObject *py_write_cr3_arm64(PyObject *self, PyObject *args) {
    unsigned long long val;
    if (!PyArg_ParseTuple(args, "K", &val)) return NULL;
    __asm__ volatile("msr ttbr0_el1, %0\nisb" :: "r"((uint64_t)val));
    Py_RETURN_NONE;
}
/* invlpg → TLBI VAE1IS */
static PyObject *py_invlpg_arm64(PyObject *self, PyObject *args) {
    unsigned long long vaddr;
    if (!PyArg_ParseTuple(args, "K", &vaddr)) return NULL;
    __asm__ volatile("tlbi vae1is, %0\ndsb sy\nisb" :: "r"(vaddr >> 12));
    Py_RETURN_NONE;
}
#endif /* ARCH_ARM64 */

// ── Arch-dispatch macros for method table ────────────────────────────────────
#ifdef ARCH_ARM64
#define HAL_INB        py_inb_arm64
#define HAL_OUTB       py_outb_arm64
#define HAL_INW        py_inb_arm64   /* no 16-bit on arm64, map to 8-bit */
#define HAL_OUTW       py_outb_arm64
#define HAL_INL        py_inb_arm64
#define HAL_OUTL       py_outb_arm64
#define HAL_READ_CR2   py_read_cr2_arm64
#define HAL_READ_CR3   py_read_cr3_arm64
#define HAL_WRITE_CR3  py_write_cr3_arm64
#define HAL_INVLPG     py_invlpg_arm64
#else
#define HAL_INB        py_inb
#define HAL_OUTB       py_outb
#define HAL_INW        py_inw
#define HAL_OUTW       py_outw
#define HAL_INL        py_inl
#define HAL_OUTL       py_outl
#define HAL_READ_CR2   py_read_cr2
#define HAL_READ_CR3   py_read_cr3
#define HAL_WRITE_CR3  py_write_cr3
#define HAL_INVLPG     py_invlpg
#endif

// ── MMIO ─────────────────────────────────────────────────────────────────────
// On arm64 io.h is not included, so provide the MMIO helpers inline here.
#ifdef ARCH_ARM64
static inline uint8_t  mmio_read8 (uintptr_t addr) { return *(volatile uint8_t  *)addr; }
static inline uint32_t mmio_read32(uintptr_t addr) { return *(volatile uint32_t *)addr; }
static inline void     mmio_write32(uintptr_t addr, uint32_t v) { *(volatile uint32_t *)addr = v; }
#endif

static PyObject *py_mmio_read8(PyObject *self, PyObject *args) {
    unsigned long long addr;
    if (!PyArg_ParseTuple(args, "K", &addr)) return NULL;
    return PyLong_FromUnsignedLong(mmio_read8((uintptr_t)addr));
}

static PyObject *py_mmio_read32(PyObject *self, PyObject *args) {
    unsigned long long addr;
    if (!PyArg_ParseTuple(args, "K", &addr)) return NULL;
    return PyLong_FromUnsignedLong(mmio_read32((uintptr_t)addr));
}

static PyObject *py_mmio_write32(PyObject *self, PyObject *args) {
    unsigned long long addr;
    unsigned int val;
    if (!PyArg_ParseTuple(args, "KI", &addr, &val)) return NULL;
    mmio_write32((uintptr_t)addr, (uint32_t)val);
    Py_RETURN_NONE;
}

static PyObject *py_mmio_write8(PyObject *self, PyObject *args) {
    unsigned long long addr;
    unsigned int val;
    if (!PyArg_ParseTuple(args, "KI", &addr, &val)) return NULL;
    *(volatile uint8_t *)(uintptr_t)addr = (uint8_t)val;
    Py_RETURN_NONE;
}

// ── PIT tick counter (incremented on every timer interrupt before Python dispatch)
extern void pit_tick(void);   // defined in src/libc/time.c (or main_arm64.c on arm64)

// ── TLB ──────────────────────────────────────────────────────────────────────

#ifndef ARCH_ARM64
static PyObject *py_invlpg(PyObject *self, PyObject *args) {
    unsigned long long vaddr;
    if (!PyArg_ParseTuple(args, "K", &vaddr)) return NULL;
    __asm__ volatile ("invlpg (%0)" :: "r"((uintptr_t)vaddr) : "memory");
    Py_RETURN_NONE;
}
#endif /* !ARCH_ARM64 */

// ── Interrupt dispatch bridge ─────────────────────────────────────────────────

// Python-side router and pending interrupt queue. The raw interrupt path cannot
// safely call into Python on SMP/no-GIL builds, so C records events and the
// Python event loop drains them from normal execution context.
static PyObject *interrupt_router   = NULL;
static PyObject *event_loop         = NULL;   // asyncio loop object
static PyObject *call_soon_ts       = NULL;   // loop.call_soon_threadsafe
static void _dbg(const char *s);

#define PENDING_IRQ_CAP 256U
#define PENDING_IRQ_DRAIN_MAX 64U

typedef struct {
    uint64_t vector;
    uint64_t error_code;
    uint64_t rip;
    uint64_t cs;
    uint64_t rflags;
    uint64_t rsp;
} pending_irq_t;

static pending_irq_t pending_irqs[PENDING_IRQ_CAP];
static volatile uint32_t pending_irq_head;
static volatile uint32_t pending_irq_tail;
static volatile uint32_t pending_irq_dropped;

#ifndef ARCH_ARM64
static uint64_t irq_save(void) {
    uint64_t flags;
    __asm__ volatile("pushfq; popq %0; cli" : "=r"(flags) :: "memory");
    return flags;
}

static void irq_restore(uint64_t flags) {
    if (flags & (1ULL << 9)) {
        __asm__ volatile("sti" ::: "memory");
    }
}
#else
static uint64_t irq_save(void) {
    uint64_t flags;
    __asm__ volatile("mrs %0, daif\nmsr daifset, #2" : "=r"(flags) :: "memory");
    return flags;
}

static void irq_restore(uint64_t flags) {
    __asm__ volatile("msr daif, %0" :: "r"(flags) : "memory");
}
#endif

static void queue_interrupt(uint64_t vector, uint64_t error_code,
                            uint64_t rip, uint64_t cs,
                            uint64_t rflags, uint64_t rsp) {
    uint32_t head = pending_irq_head;
    uint32_t next = (head + 1U) % PENDING_IRQ_CAP;
    if (next == pending_irq_tail) {
        pending_irq_dropped++;
        return;
    }

    pending_irqs[head] = (pending_irq_t){
        vector, error_code, rip, cs, rflags, rsp
    };
    __sync_synchronize();
    pending_irq_head = next;
}

static PyObject *py_set_interrupt_router(PyObject *self, PyObject *args) {
    PyObject *router;
    if (!PyArg_ParseTuple(args, "O", &router)) return NULL;
    if (!PyCallable_Check(router)) {
        PyErr_SetString(PyExc_TypeError, "router must be callable");
        return NULL;
    }
    Py_XINCREF(router);
    Py_XDECREF(interrupt_router);
    interrupt_router = router;
    Py_RETURN_NONE;
}

static PyObject *py_set_event_loop(PyObject *self, PyObject *args) {
    PyObject *loop;
    if (!PyArg_ParseTuple(args, "O", &loop)) return NULL;
    Py_XINCREF(loop);
    Py_XDECREF(event_loop);
    event_loop = loop;
    // Cache loop.call_soon_threadsafe for interrupt-context use
    Py_XDECREF(call_soon_ts);
    call_soon_ts = PyObject_GetAttrString(loop, "call_soon_threadsafe");
    Py_RETURN_NONE;
}

static PyObject *py_drain_interrupts(PyObject *self, PyObject *args) {
    (void)self;
    (void)args;

    pending_irq_t local[PENDING_IRQ_DRAIN_MAX];
    uint32_t count = 0;

    uint64_t flags = irq_save();
    while (pending_irq_tail != pending_irq_head && count < PENDING_IRQ_DRAIN_MAX) {
        local[count++] = pending_irqs[pending_irq_tail];
        pending_irq_tail = (pending_irq_tail + 1U) % PENDING_IRQ_CAP;
    }
    irq_restore(flags);

    PyObject *items = PyList_New(count);
    if (!items) {
        return NULL;
    }
    for (uint32_t i = 0; i < count; i++) {
        PyObject *item = Py_BuildValue(
            "(KKKKKK)",
            (unsigned long long)local[i].vector,
            (unsigned long long)local[i].error_code,
            (unsigned long long)local[i].rip,
            (unsigned long long)local[i].cs,
            (unsigned long long)local[i].rflags,
            (unsigned long long)local[i].rsp
        );
        if (!item) {
            Py_DECREF(items);
            return NULL;
        }
        PyList_SET_ITEM(items, i, item);
    }
    return items;
}

// Called from idt.c on every hardware/software interrupt.
// Records the interrupt for later dispatch by the Python event loop.
void interrupt_dispatch_python(uint64_t vector, uint64_t error_code,
                               uint64_t rip, uint64_t cs,
                               uint64_t rflags, uint64_t rsp) {
    // Advance C-side tick counter on every timer interrupt (vector 0x20)
    if (vector == 0x20) pit_tick();

    if (!interrupt_router) return;
    queue_interrupt(vector, error_code, rip, cs, rflags, rsp);
}

// ── Buffer address (for ctypes.addressof equivalent) ─────────────────────────
// Returns the address of the underlying C buffer for bytearray (or subclass).
// On bare metal with identity mapping, this virtual address IS the physical addr.
static PyObject *py_buf_addr(PyObject *self, PyObject *args) {
    PyObject *obj;
    if (!PyArg_ParseTuple(args, "O", &obj)) return NULL;
    if (!PyByteArray_Check(obj)) {
        PyErr_SetString(PyExc_TypeError, "buf_addr requires bytearray");
        return NULL;
    }
    uintptr_t addr = (uintptr_t)PyByteArray_AS_STRING(obj);
    return PyLong_FromUnsignedLongLong((unsigned long long)addr);
}

// ── DMA allocation ────────────────────────────────────────────────────────────
// Allocate zero-filled C-heap memory that Python's GC will never touch.
// Returns the physical address (= virtual on identity-mapped bare metal).
// Memory is never freed — caller is responsible for lifetime.
extern void *calloc(size_t n, size_t size);
static PyObject *py_dma_alloc(PyObject *self, PyObject *args) {
    unsigned long long size;
    if (!PyArg_ParseTuple(args, "K", &size)) return NULL;
    /* VirtIO queues must be page-aligned (pfn = ptr >> 12 must satisfy ptr == pfn*4096).
     * Allocate an extra page so we can round up to the next 4096-byte boundary.
     * The wasted prefix bytes are never returned; no free() so no leak concern. */
    char *raw = (char *)calloc(1, (size_t)size + 4096);
    if (!raw) {
        PyErr_NoMemory();
        return NULL;
    }
    uintptr_t aligned = ((uintptr_t)raw + 4095) & ~(uintptr_t)4095;
    return PyLong_FromUnsignedLongLong((unsigned long long)aligned);
}

static PyObject *py_serial_write(PyObject *self, PyObject *args) {
    const char *text;
    if (!PyArg_ParseTuple(args, "s", &text)) return NULL;
    _dbg(text);
    Py_RETURN_NONE;
}

// ── C-level pthread smoke test ────────────────────────────────────────────────

static void *pthread_selftest_worker(void *arg) {
    volatile uint64_t *marker = (volatile uint64_t *)arg;
    *marker = 123456789ULL;
    return (void *)(uintptr_t)0x1234ULL;
}

static PyObject *py_pthread_selftest(PyObject *self, PyObject *args) {
    static volatile uint64_t marker;
    marker = 0;

    pthread_t tid;
    int rc = pthread_create(&tid, NULL, pthread_selftest_worker, (void *)&marker);
    if (rc != 0) {
        return Py_BuildValue("(iKK)", rc, 0ULL, 0ULL);
    }

    void *retval = NULL;
    rc = pthread_join(tid, &retval);
    return Py_BuildValue(
        "(iKK)",
        rc,
        (unsigned long long)marker,
        (unsigned long long)(uintptr_t)retval
    );
}

// Exercises the pthread attr / condattr surface that PythonOS exposes for
// source-compatibility, plus a non-NULL-attr pthread_create + join. CPython
// itself does not call into the attr path on PythonOS (see
// docs/pthread-attr-coverage.md), so this helper exists to keep that
// surface verified independently.
static PyObject *py_pthread_attr_selftest(PyObject *self, PyObject *args) {
    int cases = 0;
    const char *fail = NULL;

    do {
        // attr_init / destroy round-trip with valid pointers.
        pthread_attr_t attrs;
        if (pthread_attr_init(&attrs) != 0) { fail = "attr_init"; break; }
        cases++;
        if (pthread_attr_destroy(&attrs) != 0) { fail = "attr_destroy"; break; }
        cases++;

        // attr_init rejects NULL.
        if (pthread_attr_init(NULL) != EINVAL) { fail = "attr_init(NULL) accepted"; break; }
        cases++;

        // detachstate accepts known values.
        if (pthread_attr_init(&attrs) != 0) { fail = "attr_init/2"; break; }
        if (pthread_attr_setdetachstate(&attrs, PTHREAD_CREATE_JOINABLE) != 0) {
            fail = "setdetachstate(JOINABLE)"; break;
        }
        cases++;
        if (pthread_attr_setdetachstate(&attrs, PTHREAD_CREATE_DETACHED) != 0) {
            fail = "setdetachstate(DETACHED)"; break;
        }
        cases++;
        if (pthread_attr_setdetachstate(&attrs, 99) != EINVAL) {
            fail = "setdetachstate(99) accepted"; break;
        }
        cases++;

        // stacksize: under 32 KiB rejected, valid round-trips through getter.
        if (pthread_attr_setstacksize(&attrs, 1024) != EINVAL) {
            fail = "setstacksize(1024) accepted"; break;
        }
        cases++;
        if (pthread_attr_setstacksize(&attrs, 131072) != 0) {
            fail = "setstacksize(131072)"; break;
        }
        cases++;
        size_t got = 0;
        if (pthread_attr_getstacksize(&attrs, &got) != 0 || got != 131072) {
            fail = "getstacksize round-trip"; break;
        }
        cases++;
        if (pthread_attr_getstacksize(NULL, &got) != EINVAL) {
            fail = "getstacksize(NULL,&) accepted"; break;
        }
        cases++;
        if (pthread_attr_getstacksize(&attrs, NULL) != EINVAL) {
            fail = "getstacksize(&,NULL) accepted"; break;
        }
        cases++;

        // Non-NULL-attr pthread_create + join, exercising the path CPython
        // *would* use if THREAD_STACK_SIZE were defined.
        if (pthread_attr_setdetachstate(&attrs, PTHREAD_CREATE_JOINABLE) != 0) {
            fail = "setdetachstate(JOINABLE)/2"; break;
        }
        static volatile uint64_t attr_marker;
        attr_marker = 0;
        pthread_t tid;
        if (pthread_create(&tid, &attrs, pthread_selftest_worker,
                           (void *)&attr_marker) != 0) {
            fail = "create with attr"; break;
        }
        cases++;
        void *retval = NULL;
        if (pthread_join(tid, &retval) != 0) {
            fail = "join with attr"; break;
        }
        cases++;
        if (attr_marker != 123456789ULL || (uintptr_t)retval != 0x1234ULL) {
            fail = "attr worker marker"; break;
        }
        cases++;
        if (pthread_attr_destroy(&attrs) != 0) { fail = "attr_destroy/2"; break; }
        cases++;

        // condattr surface is no-op stubs in our build (CONDATTR_MONOTONIC
        // is not defined). Verify the calls succeed and accept the
        // documented clock values.
        pthread_condattr_t ca;
        if (pthread_condattr_init(&ca) != 0) { fail = "condattr_init"; break; }
        cases++;
        // Accepts CLOCK_REALTIME and CLOCK_MONOTONIC silently (stub).
        if (pthread_condattr_setclock(&ca, CLOCK_REALTIME) != 0) {
            fail = "condattr_setclock(REALTIME)"; break;
        }
        cases++;
        if (pthread_condattr_setclock(&ca, CLOCK_MONOTONIC) != 0) {
            fail = "condattr_setclock(MONOTONIC)"; break;
        }
        cases++;
        if (pthread_condattr_destroy(&ca) != 0) { fail = "condattr_destroy"; break; }
        cases++;

        // Mutex attr surface (used by CPython for PyThread_type_lock mutex
        // init via NULL attr; settype is called in some paths).
        pthread_mutexattr_t ma;
        if (pthread_mutexattr_init(&ma) != 0) { fail = "mutexattr_init"; break; }
        cases++;
        if (pthread_mutexattr_settype(&ma, PTHREAD_MUTEX_NORMAL) != 0) {
            fail = "mutexattr_settype"; break;
        }
        cases++;
        if (pthread_mutexattr_destroy(&ma) != 0) { fail = "mutexattr_destroy"; break; }
        cases++;
    } while (0);

    if (fail) {
        return Py_BuildValue("(is)", cases, fail);
    }
    return Py_BuildValue("(iO)", cases, Py_None);
}

// ── Module definition ─────────────────────────────────────────────────────────

static PyMethodDef hal_methods[] = {
    {"inb",                  HAL_INB,                 METH_VARARGS, "Read byte from I/O port"},
    {"inw",                  HAL_INW,                 METH_VARARGS, "Read word from I/O port"},
    {"inl",                  HAL_INL,                 METH_VARARGS, "Read dword from I/O port"},
    {"outb",                 HAL_OUTB,                METH_VARARGS, "Write byte to I/O port"},
    {"outw",                 HAL_OUTW,                METH_VARARGS, "Write word to I/O port"},
    {"outl",                 HAL_OUTL,                METH_VARARGS, "Write dword to I/O port"},
    {"read_cr2",             HAL_READ_CR2,            METH_VARARGS, "Read CR2 / FAR_EL1 (fault address)"},
    {"read_cr3",             HAL_READ_CR3,            METH_VARARGS, "Read CR3 / TTBR0_EL1 (page table base)"},
    {"write_cr3",            HAL_WRITE_CR3,           METH_VARARGS, "Write CR3 / TTBR0_EL1"},
    {"mmio_read8",           py_mmio_read8,           METH_VARARGS, "MMIO read byte"},
    {"mmio_read32",          py_mmio_read32,          METH_VARARGS, "MMIO read dword"},
    {"mmio_write32",         py_mmio_write32,         METH_VARARGS, "MMIO write dword"},
    {"mmio_write8",          py_mmio_write8,          METH_VARARGS, "MMIO write byte"},
    {"invlpg",               HAL_INVLPG,              METH_VARARGS, "Invalidate TLB entry"},
    {"set_interrupt_router", py_set_interrupt_router, METH_VARARGS, "Register Python interrupt dispatcher"},
    {"set_event_loop",       py_set_event_loop,       METH_VARARGS, "Register asyncio event loop for threadsafe dispatch"},
    {"drain_interrupts",     py_drain_interrupts,     METH_NOARGS,  "Drain pending hardware interrupts"},
    {"buf_addr",             py_buf_addr,             METH_VARARGS, "Return physical address of a buffer object's data"},
    {"dma_alloc",            py_dma_alloc,            METH_VARARGS, "Allocate zero-filled C-heap DMA buffer, return physical address"},
    {"serial_write",         py_serial_write,         METH_VARARGS, "Write raw text to the early serial console"},
    {"pthread_selftest",     py_pthread_selftest,     METH_NOARGS,  "Run a C-level pthread_create/join smoke test"},
    {"pthread_attr_selftest",py_pthread_attr_selftest,METH_NOARGS,  "Exercise pthread_attr_* / pthread_condattr_* / pthread_mutexattr_* surface"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef hal_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_hal",
    .m_doc = NULL,
    .m_size = -1,
    .m_methods = hal_methods,
};

PyMODINIT_FUNC PyInit__hal(void) {
    PyObject *m = PyModule_Create(&hal_module);
    if (!m) return NULL;
#ifdef Py_GIL_DISABLED
    PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED);
#endif
#ifdef ARCH_ARM64
    PyModule_AddStringConstant(m, "ARCH", "arm64");
#else
    PyModule_AddStringConstant(m, "ARCH", "x86_64");
#endif
    PyModule_AddIntConstant(m, "SMP_CPUS", (long)smp_cpu_count());
    PyModule_AddIntConstant(m, "SMP_ONLINE", (long)smp_online_count());
    PyModule_AddIntConstant(m, "SMP_WORKERS", (long)smp_worker_selftest_count());
    PyModule_AddIntConstant(m, "BSP_APIC_ID", (long)smp_bsp_apic_id());
#ifdef Py_GIL_DISABLED
    PyModule_AddIntConstant(m, "PY_GIL_DISABLED", 1);
#else
    PyModule_AddIntConstant(m, "PY_GIL_DISABLED", 0);
#endif
    return m;
}

// ── Python kernel entry point ─────────────────────────────────────────────────

typedef struct { uint64_t base; uint64_t length; } mmap_entry_t;

typedef struct {
    uint64_t phys_addr;
    uint32_t pitch;
    uint32_t width;
    uint32_t height;
    uint8_t  bpp;
    uint8_t  type;
    uint8_t  valid;
} framebuffer_info_t;

// Simple serial write for C-level debug (before Python stdout is up)
static void _dbg(const char *s) {
#ifdef ARCH_ARM64
    for (; *s; s++) {
        volatile uint32_t *fr = (volatile uint32_t *)(0x09000018UL);
        volatile uint32_t *dr = (volatile uint32_t *)(0x09000000UL);
        while (*fr & (1U << 5)) {}
        if (*s == '\n') { while (*fr & (1U << 5)) {} *dr = '\r'; }
        *dr = (uint32_t)(unsigned char)*s;
    }
#else
    for (; *s; s++) {
        while ((inb(0x3F8 + 5) & 0x20) == 0) {}
        if (*s == '\n') { while ((inb(0x3F8 + 5) & 0x20) == 0) {} outb(0x3F8, '\r'); }
        outb(0x3F8, (uint8_t)*s);
    }
#endif
}

/* Merge kernel frozen modules with the CPython
 * standard frozen modules (bootstrap, codecs, io, …) before Py_Initialize
 * so that both sets are available during interpreter startup. */
extern void install_frozen_kernel(void);

void python_kernel_start(mmap_entry_t *mmap, int mmap_count,
                         framebuffer_info_t *fb) {
    _dbg("[hal] AppendInittab\n");
    PyImport_AppendInittab("_hal", &PyInit__hal);

    _dbg("[hal] installing frozen modules\n");
    install_frozen_kernel();

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0;
#ifdef Py_GIL_DISABLED
    config.tlbc_enabled = 0;
#endif
    _dbg("[hal] Py_Initialize starting\n");
    Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    _dbg("[hal] Py_Initialize done\n");

    // Memory map: list of (base, length) tuples
    PyObject *py_mmap = PyList_New(mmap_count);
    for (int i = 0; i < mmap_count; i++) {
        PyList_SET_ITEM(py_mmap, i,
            Py_BuildValue("(KK)", mmap[i].base, mmap[i].length));
    }

    // Framebuffer info dict (or None if not available)
    PyObject *py_fb;
    if (fb && fb->valid) {
        py_fb = Py_BuildValue(
            "{sKsIsIsIsIsI}",
            "phys_addr", (unsigned long long)fb->phys_addr,
            "pitch",     (unsigned int)fb->pitch,
            "width",     (unsigned int)fb->width,
            "height",    (unsigned int)fb->height,
            "bpp",       (unsigned int)fb->bpp,
            "type",      (unsigned int)fb->type
        );
    } else {
        py_fb = Py_None;
        Py_INCREF(Py_None);
    }

    _dbg("[hal] importing kernel\n");
    PyObject *kernel = PyImport_ImportModule("kernel");
#ifdef ARCH_ARM64
    if (!kernel) { _dbg("[hal] kernel import FAILED\n"); PyErr_Print(); for(;;) __asm__ volatile("wfe"); }
#else
    if (!kernel) { _dbg("[hal] kernel import FAILED\n"); PyErr_Print(); for(;;) __asm__("hlt"); }
#endif
    _dbg("[hal] kernel imported\n");

    PyObject *boot_fn = PyObject_GetAttrString(kernel, "boot");
#ifdef ARCH_ARM64
    if (!boot_fn)  { _dbg("[hal] boot attr FAILED\n"); PyErr_Print(); for(;;) __asm__ volatile("wfe"); }
#else
    if (!boot_fn)  { _dbg("[hal] boot attr FAILED\n"); PyErr_Print(); for(;;) __asm__("hlt"); }
#endif

    _dbg("[hal] calling boot()\n");
    PyObject *result = PyObject_CallFunction(boot_fn, "OO", py_mmap, py_fb);
#ifdef ARCH_ARM64
    if (!result)   { _dbg("[hal] boot() FAILED\n"); PyErr_Print(); for(;;) __asm__ volatile("wfe"); }
#else
    if (!result)   { _dbg("[hal] boot() FAILED\n"); PyErr_Print(); for(;;) __asm__("hlt"); }
#endif

    Py_DECREF(result);
    Py_DECREF(boot_fn);
    Py_DECREF(kernel);
    Py_DECREF(py_mmap);
    Py_DECREF(py_fb);
}

/* posixmodule.c, pwdmodule.c, and PyOS_FSPath are now compiled and linked
 * from CPython's source tree — no stubs needed here. */
