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
#include "../boot/io.h"

// ── Port I/O ────────────────────────────────────────────────────────────────

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

// ── Control registers ────────────────────────────────────────────────────────

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

// ── MMIO ─────────────────────────────────────────────────────────────────────

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

// ── PIT tick counter (incremented on every timer interrupt before Python dispatch)
extern void pit_tick(void);   // defined in src/libc/time.c

// ── TLB ──────────────────────────────────────────────────────────────────────

static PyObject *py_invlpg(PyObject *self, PyObject *args) {
    unsigned long long vaddr;
    if (!PyArg_ParseTuple(args, "K", &vaddr)) return NULL;
    __asm__ volatile ("invlpg (%0)" :: "r"((uintptr_t)vaddr) : "memory");
    Py_RETURN_NONE;
}

// ── Interrupt dispatch bridge ─────────────────────────────────────────────────

// Python-side router and asyncio event loop for thread-safe scheduling
static PyObject *interrupt_router   = NULL;
static PyObject *event_loop         = NULL;   // asyncio loop object
static PyObject *call_soon_ts       = NULL;   // loop.call_soon_threadsafe

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

// Called from idt.c on every hardware/software interrupt.
// Routes through call_soon_threadsafe so the handler runs in the event loop
// thread rather than inline in interrupt context.
void interrupt_dispatch_python(uint64_t vector, uint64_t error_code,
                               uint64_t rip, uint64_t cs,
                               uint64_t rflags, uint64_t rsp) {
    // Advance C-side tick counter on every timer interrupt (vector 0x20)
    if (vector == 0x20) pit_tick();

    if (!interrupt_router) return;

    if (call_soon_ts) {
        // Safe path: schedule handler onto the event loop from interrupt context
        PyObject *r = PyObject_CallFunction(
            call_soon_ts, "OKKKKKK",
            interrupt_router, vector, error_code, rip, cs, rflags, rsp
        );
        Py_XDECREF(r);
    } else {
        // Early boot (no event loop yet): call directly
        PyObject *r = PyObject_CallFunction(
            interrupt_router, "KKKKKK",
            vector, error_code, rip, cs, rflags, rsp
        );
        if (!r) PyErr_Print();
        Py_XDECREF(r);
    }
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
    void *ptr = calloc(1, (size_t)size);
    if (!ptr) {
        PyErr_NoMemory();
        return NULL;
    }
    return PyLong_FromUnsignedLongLong((unsigned long long)(uintptr_t)ptr);
}

// ── Module definition ─────────────────────────────────────────────────────────

static PyMethodDef hal_methods[] = {
    {"inb",                  py_inb,                  METH_VARARGS, "Read byte from I/O port"},
    {"inw",                  py_inw,                  METH_VARARGS, "Read word from I/O port"},
    {"inl",                  py_inl,                  METH_VARARGS, "Read dword from I/O port"},
    {"outb",                 py_outb,                 METH_VARARGS, "Write byte to I/O port"},
    {"outw",                 py_outw,                 METH_VARARGS, "Write word to I/O port"},
    {"outl",                 py_outl,                 METH_VARARGS, "Write dword to I/O port"},
    {"read_cr2",             py_read_cr2,             METH_NOARGS,  "Read CR2 (page fault address)"},
    {"read_cr3",             py_read_cr3,             METH_NOARGS,  "Read CR3 (page table base)"},
    {"write_cr3",            py_write_cr3,            METH_VARARGS, "Write CR3"},
    {"mmio_read8",           py_mmio_read8,           METH_VARARGS, "MMIO read byte"},
    {"mmio_read32",          py_mmio_read32,          METH_VARARGS, "MMIO read dword"},
    {"mmio_write32",         py_mmio_write32,         METH_VARARGS, "MMIO write dword"},
    {"invlpg",               py_invlpg,               METH_VARARGS, "Invalidate TLB entry"},
    {"set_interrupt_router", py_set_interrupt_router, METH_VARARGS, "Register Python interrupt dispatcher"},
    {"set_event_loop",       py_set_event_loop,       METH_VARARGS, "Register asyncio event loop for threadsafe dispatch"},
    {"buf_addr",             py_buf_addr,             METH_VARARGS, "Return physical address of a buffer object's data"},
    {"dma_alloc",            py_dma_alloc,            METH_VARARGS, "Allocate zero-filled C-heap DMA buffer, return physical address"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef hal_module = {
    PyModuleDef_HEAD_INIT, "_hal", NULL, -1, hal_methods
};

PyMODINIT_FUNC PyInit__hal(void) {
    return PyModule_Create(&hal_module);
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
    for (; *s; s++) {
        while ((inb(0x3F8 + 5) & 0x20) == 0) {}
        if (*s == '\n') { while ((inb(0x3F8 + 5) & 0x20) == 0) {} outb(0x3F8, '\r'); }
        outb(0x3F8, (uint8_t)*s);
    }
}

/* Merge kernel frozen modules (encodings + kernel/*) with the CPython
 * standard frozen modules (bootstrap, codecs, io, …) before Py_Initialize
 * so that both sets are available during interpreter startup. */
extern void install_frozen_kernel(void);

void python_kernel_start(mmap_entry_t *mmap, int mmap_count,
                         framebuffer_info_t *fb) {
    _dbg("[hal] AppendInittab\n");
    PyImport_AppendInittab("_hal", &PyInit__hal);

    _dbg("[hal] installing frozen modules\n");
    install_frozen_kernel();

    Py_NoSiteFlag            = 1;
    Py_NoUserSiteDirectory   = 1;
    Py_IgnoreEnvironmentFlag = 1;
    _dbg("[hal] Py_Initialize starting\n");
    Py_Initialize();
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
    if (!kernel) { _dbg("[hal] kernel import FAILED\n"); PyErr_Print(); for(;;) __asm__("hlt"); }
    _dbg("[hal] kernel imported\n");

    PyObject *boot_fn = PyObject_GetAttrString(kernel, "boot");
    if (!boot_fn)  { _dbg("[hal] boot attr FAILED\n"); PyErr_Print(); for(;;) __asm__("hlt"); }

    _dbg("[hal] calling boot()\n");
    PyObject *result = PyObject_CallFunction(boot_fn, "OO", py_mmap, py_fb);
    if (!result)   { _dbg("[hal] boot() FAILED\n"); PyErr_Print(); for(;;) __asm__("hlt"); }

    Py_DECREF(result);
    Py_DECREF(boot_fn);
    Py_DECREF(kernel);
    Py_DECREF(py_mmap);
    Py_DECREF(py_fb);
}

/* PyOS_FSPath — defined in posixmodule.c which we exclude.
 * Accept str/bytes directly; call __fspath__ on path-like objects.
 * Uses only public Python C API so hal.c can be compiled without pycore_*.h. */
PyObject *
PyOS_FSPath(PyObject *path)
{
    if (PyUnicode_Check(path) || PyBytes_Check(path)) {
        Py_INCREF(path);
        return path;
    }
    PyObject *func = PyObject_GetAttrString(path, "__fspath__");
    if (func == NULL) {
        PyErr_Format(PyExc_TypeError,
                     "expected str, bytes or os.PathLike object, "
                     "not %.200s",
                     Py_TYPE(path)->tp_name);
        return NULL;
    }
    PyObject *result = PyObject_CallNoArgs(func);
    Py_DECREF(func);
    if (result == NULL) {
        return NULL;
    }
    if (!PyUnicode_Check(result) && !PyBytes_Check(result)) {
        PyErr_Format(PyExc_TypeError,
                     "expected __fspath__() to return str or bytes, not %.200s",
                     Py_TYPE(result)->tp_name);
        Py_DECREF(result);
        return NULL;
    }
    return result;
}

/* ── Minimal posix stub ──────────────────────────────────────────────────────
 * importlib._bootstrap_external does `import posix as _os` unconditionally on
 * non-Windows. It doesn't call any _os methods at import time (for the 'linux'
 * platform path), but the module must exist and return a valid object.
 * At runtime, FileFinder.find_spec() calls _os.stat() and catches OSError, so
 * we raise ENOENT there. listdir() returns [] so the cache stays empty and all
 * imports fall through to FrozenImporter. */
static PyObject *_posix_enoent(PyObject *s, PyObject *a) {
    PyErr_SetString(PyExc_FileNotFoundError, "no filesystem on bare metal");
    return NULL;
}
static PyObject *_posix_getcwd(PyObject *s, PyObject *a) {
    return PyUnicode_FromString("/");
}
static PyObject *_posix_listdir(PyObject *s, PyObject *a) {
    return PyList_New(0);
}
static PyObject *_posix_fspath(PyObject *s, PyObject *a) {
    PyObject *p;
    if (!PyArg_ParseTuple(a, "O", &p)) return NULL;
    Py_INCREF(p);
    return p;
}
static PyMethodDef _posix_methods[] = {
    {"stat",    _posix_enoent,  METH_VARARGS, NULL},
    {"lstat",   _posix_enoent,  METH_VARARGS, NULL},
    {"getcwd",  _posix_getcwd,  METH_NOARGS,  NULL},
    {"listdir", _posix_listdir, METH_VARARGS, NULL},
    {"fspath",  _posix_fspath,  METH_VARARGS, NULL},
    {"open",    _posix_enoent,  METH_VARARGS, NULL},
    {"replace", _posix_enoent,  METH_VARARGS, NULL},
    {"unlink",  _posix_enoent,  METH_VARARGS, NULL},
    {"mkdir",   _posix_enoent,  METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef _posix_def = {
    PyModuleDef_HEAD_INIT, "posix", NULL, -1, _posix_methods
};
PyMODINIT_FUNC PyInit_posix(void) {
    PyObject *m = PyModule_Create(&_posix_def);
    if (!m) return NULL;
    PyObject *env = PyDict_New();
    if (!env) { Py_DECREF(m); return NULL; }
    if (PyModule_AddObject(m, "environ", env) < 0) {
        Py_DECREF(env); Py_DECREF(m); return NULL;
    }
    if (PyModule_AddStringConstant(m, "sep", "/") < 0) {
        Py_DECREF(m); return NULL;
    }
    return m;
}
PyMODINIT_FUNC PyInit__weakrefset(void){ return NULL; }
PyMODINIT_FUNC PyInit__hashlib(void)   { return NULL; }
PyMODINIT_FUNC PyInit__ssl(void)       { return NULL; }
/* _sha1/_md5 excluded (HACL dependency); stubs for old config.c compatibility */
PyMODINIT_FUNC PyInit__sha1(void)      { return NULL; }
PyMODINIT_FUNC PyInit__md5(void)       { return NULL; }
/* pwd excluded: pwdmodule.c requires getpwuid/getpwnam/uid+gid helpers */
PyMODINIT_FUNC PyInit_pwd(void)        { return NULL; }
