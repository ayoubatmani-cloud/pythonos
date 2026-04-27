/*
 * syscalls.c — POSIX stubs.
 *
 * CPython calls these. Most are no-ops or return sensible defaults.
 * Real implementations come later as kernel subsystems mature.
 */

#include "include/libc.h"
#include "../boot/io.h"
#include <stdint.h>

// ── Process ───────────────────────────────────────────────────────────────────

void abort(void) {
    // Disable interrupts and halt — this is a kernel panic path
    __asm__ volatile ("cli");
    for (;;) __asm__ volatile ("hlt");
}

void exit(int code) {
    (void)code;
    abort();
}

void _exit(int code) { exit(code); }

int getpid(void) { return 1; }    // kernel is PID 1

int getpagesize(void) { return 4096; }

// ── Environment ───────────────────────────────────────────────────────────────

char *getenv(const char *name) { (void)name; return NULL; }

int setenv(const char *name, const char *val, int overwrite) {
    (void)name; (void)val; (void)overwrite;
    return -1;
}

int unsetenv(const char *name) { (void)name; return 0; }

// ── Signals ───────────────────────────────────────────────────────────────────

static sighandler_t _signal_handlers[32] = {0};

sighandler_t signal(int sig, sighandler_t handler) {
    if (sig < 0 || sig >= 32) return SIG_ERR;
    sighandler_t old = _signal_handlers[sig];
    _signal_handlers[sig] = handler;
    return old;
}

int raise(int sig) {
    if (sig >= 0 && sig < 32 && _signal_handlers[sig] &&
        _signal_handlers[sig] != SIG_IGN)
        _signal_handlers[sig](sig);
    return 0;
}

int sigaction(int sig, const struct_sigaction *act, struct_sigaction *old) {
    if (old) {
        old->sa_handler = (sig >= 0 && sig < 32) ? _signal_handlers[sig] : SIG_DFL;
        old->sa_mask    = 0;
        old->sa_flags   = 0;
    }
    if (act && sig >= 0 && sig < 32)
        _signal_handlers[sig] = act->sa_handler;
    return 0;
}

int sigprocmask(int how, const sigset_t *set, sigset_t *old) {
    (void)how; (void)set;
    if (old) *old = 0;
    return 0;
}

int sigemptyset(sigset_t *set)           { if (set) *set = 0; return 0; }
int sigfillset(sigset_t *set)            { if (set) *set = ~(sigset_t)0; return 0; }
int sigaddset(sigset_t *set, int sig)    { if (set) *set |= (sigset_t)1 << sig; return 0; }
int sigdelset(sigset_t *set, int sig)    { if (set) *set &= ~((sigset_t)1 << sig); return 0; }
int sigismember(const sigset_t *set, int sig) {
    return (set && (*set >> sig) & 1) ? 1 : 0;
}

// ── File system (CPython open/read/write — redirected to frozen modules) ──────

// CPython uses these for loading .py files. With frozen modules we never
// hit the filesystem during import. These stubs exist for completeness
// and to allow CPython to open /dev/urandom etc.

int open(const char *path, int flags, ...) {
    (void)path; (void)flags;
    errno = ENOSYS;
    return -1;
}

int close(int fd) { (void)fd; return 0; }

long read(int fd, void *buf, size_t n) {
    (void)fd; (void)buf; (void)n;
    errno = ENOSYS;
    return -1;
}

long write(int fd, const void *buf, size_t n) {
    // fd 1 = stdout, fd 2 = stderr — both go to serial
    if (fd == 1 || fd == 2) {
        const char *p = buf;
        for (size_t i = 0; i < n; i++) {
            while ((inb(0x3F8 + 5) & 0x20) == 0) {}
            if (p[i] == '\n') { while ((inb(0x3F8 + 5) & 0x20) == 0) {} outb(0x3F8, '\r'); }
            outb(0x3F8, p[i]);
        }
        return (long)n;
    }
    errno = ENOSYS;
    return -1;
}

long lseek(int fd, long offset, int whence) {
    (void)fd; (void)offset; (void)whence;
    errno = ENOSYS;
    return -1;
}

int stat(const char *path, void *buf) {
    (void)path; (void)buf;
    errno = ENOENT;
    return -1;
}

int fstat(int fd, void *buf) { (void)fd; (void)buf; errno = ENOSYS; return -1; }
int lstat(const char *path, void *buf) { (void)path; (void)buf; errno = ENOENT; return -1; }
int access(const char *path, int mode) { (void)path; (void)mode; errno = ENOENT; return -1; }

int fcntl(int fd, int cmd, ...) { (void)fd; (void)cmd; return 0; }
int ioctl(int fd, unsigned long req, ...) { (void)fd; (void)req; errno = ENOSYS; return -1; }

// ── Memory mapping ────────────────────────────────────────────────────────────

#define PROT_READ  1
#define PROT_WRITE 2
#define MAP_PRIVATE 2
#define MAP_ANON    0x20
#define MAP_FAILED  ((void *)-1)

void *mmap(void *addr, size_t length, int prot, int flags, int fd, long offset) {
    (void)addr; (void)prot; (void)flags; (void)fd; (void)offset;
    // mmap(MAP_ANONYMOUS) must return zeroed pages — use calloc to match that contract
    void *p = calloc(1, length);
    return p ? p : MAP_FAILED;
}

int munmap(void *addr, size_t length) {
    (void)length;
    free(addr);   // matches our mmap → malloc above
    return 0;
}

/* glibc internal: returns pointer to the thread-local errno variable.
 * Single-threaded bare metal: errno is a plain global in stdio.c. */
extern int errno;
int *__errno_location(void) { return &errno; }

int mprotect(void *addr, size_t len, int prot) {
    (void)addr; (void)len; (void)prot;
    return 0;
}

// ── Random ────────────────────────────────────────────────────────────────────

// CPython uses /dev/urandom; we provide a simple LFSR-based PRNG instead
static uint64_t _rng_state = 0xDEADBEEFCAFEBABEull;

static uint64_t _rand64(void) {
    _rng_state ^= _rng_state << 13;
    _rng_state ^= _rng_state >> 7;
    _rng_state ^= _rng_state << 17;
    return _rng_state;
}

int getrandom(void *buf, size_t n, unsigned int flags) {
    (void)flags;
    size_t total = n;
    uint8_t *b = buf;
    while (n >= 8) { uint64_t r = _rand64(); __builtin_memcpy(b, &r, 8); b += 8; n -= 8; }
    if (n) { uint64_t r = _rand64(); __builtin_memcpy(b, &r, n); }
    return (int)total;  // return bytes generated, not 0 — CPython loops until satisfied
}

// ── Locale ────────────────────────────────────────────────────────────────────

static struct lconv _lconv = { ".", "" };

char *setlocale(int category, const char *locale) {
    (void)category; (void)locale;
    return "C";
}

struct lconv *localeconv(void) { return &_lconv; }

// ── Misc ──────────────────────────────────────────────────────────────────────

unsigned int sleep(unsigned int seconds) { (void)seconds; return 0; }
int usleep(unsigned int us) { (void)us; return 0; }
int nanosleep(const struct timespec *req, struct timespec *rem) {
    (void)req; (void)rem; return 0;
}

int pause(void) { errno = EINTR; return -1; }

int isatty(int fd) { return fd == 1 || fd == 2; }

long syscall(long number, ...) { (void)number; return 1; }

void *dlopen(const char *file, int mode) { (void)file; (void)mode; return NULL; }
void *dlsym(void *handle, const char *sym) { (void)handle; (void)sym; return NULL; }
int   dlclose(void *handle) { (void)handle; return 0; }
char *dlerror(void) { return "dynamic loading not supported"; }

// ── langinfo ──────────────────────────────────────────────────────────────────

#include <langinfo.h>
char *nl_langinfo(nl_item item) {
    (void)item;
    return "";  /* bare-metal: everything is "C" locale */
}

// ── mkstemp ───────────────────────────────────────────────────────────────────

int mkstemp(char *tmpl) { (void)tmpl; return -1; }

// ── stdio stubs (glibc provides these via libc.so; we stub them) ──────────────
// FILE* ABI is pointer-compatible with glibc's struct _IO_FILE*.

void clearerr(FILE *f) { (void)f; }
void setbuf(FILE *f, char *buf) { (void)f; (void)buf; }

char *strerror(int errnum) { (void)errnum; return "Error"; }

// ── Missing unistd stubs ──────────────────────────────────────────────────────

char *getcwd(char *buf, size_t size) {
    if (buf && size > 0) { buf[0] = '/'; buf[1] = '\0'; }
    return buf;
}

// ── stdio stubs not inlined by glibc in freestanding mode ────────────────────

int putc(int c, FILE *f) { return fputc(c, f); }
int getc(FILE *f) { (void)f; return -1; }
void rewind(FILE *f) { fseek(f, 0, 0 /* SEEK_SET */); }

// ── glibc internals referenced by CPython ────────────────────────────────────
// glibc's signal.h renames calls to signal() to __sysv_signal at the call
// site. Our signal() is compiled without glibc's signal.h so it keeps the
// plain "signal" symbol. Provide __sysv_signal as a global alias.
__asm__(".globl __sysv_signal\n\t.set __sysv_signal, signal");

// glibc ctype tables: code compiled against glibc headers calls __ctype_b_loc()
// instead of isalnum() etc. We provide static ASCII-only tables.
// Flag bit layout: little-endian x86-64 (bits 8+ shift left 8, bits 0-7 stay)
// _ISblank=0x0001 _IScntrl=0x0002 _ISpunct=0x0004 _ISalnum=0x0008
// _ISupper=0x0100 _ISlower=0x0200 _ISalpha=0x0400 _ISdigit=0x0800
// _ISxdigit=0x1000 _ISspace=0x2000 _ISprint=0x4000 _ISgraph=0x8000

static const unsigned short _ctype_b_data[384] = {
    // entries 0-127: for chars -128..-1 (signed), all zero
    // entries 128-383: for chars 0..255
    [128+0  ... 128+8]   = 0x0002u,  // NUL-BS: cntrl
    [128+9]              = 0x2003u,  // TAB: cntrl|space|blank
    [128+10 ... 128+13]  = 0x2002u,  // LF,VT,FF,CR: cntrl|space
    [128+14 ... 128+31]  = 0x0002u,  // SO-US: cntrl
    [128+32]             = 0x6001u,  // SP: print|space|blank
    [128+33 ... 128+47]  = 0xC004u,  // !-/ : print|graph|punct
    [128+48 ... 128+57]  = 0xD808u,  // 0-9: print|graph|digit|xdigit|alnum
    [128+58 ... 128+64]  = 0xC004u,  // :-@ : print|graph|punct
    [128+65 ... 128+70]  = 0xD508u,  // A-F: print|graph|upper|alpha|xdigit|alnum
    [128+71 ... 128+90]  = 0xC508u,  // G-Z: print|graph|upper|alpha|alnum
    [128+91 ... 128+96]  = 0xC004u,  // [-` : print|graph|punct
    [128+97 ... 128+102] = 0xD608u,  // a-f: print|graph|lower|alpha|xdigit|alnum
    [128+103 ... 128+122]= 0xC608u,  // g-z: print|graph|lower|alpha|alnum
    [128+123 ... 128+126]= 0xC004u,  // {-~: print|graph|punct
    [128+127]            = 0x0002u,  // DEL: cntrl
    // 128-255: 0 (non-ASCII — unclassified in ASCII-only locale)
};

static const unsigned short *_ctype_b_ptr = &_ctype_b_data[128];

// toupper/tolower tables: (*ptr)[c] = converted character
static int32_t _ctype_toupper_tbl[384];
static int32_t _ctype_tolower_tbl[384];

static void _init_case_tables(void) {
    for (int i = 0; i < 384; i++) {
        int c = i - 128;
        _ctype_toupper_tbl[i] = (c >= 'a' && c <= 'z') ? c - 32 : c;
        _ctype_tolower_tbl[i] = (c >= 'A' && c <= 'Z') ? c + 32 : c;
    }
}

static int _case_tables_ready = 0;
static void _ensure_case_tables(void) {
    if (!_case_tables_ready) { _init_case_tables(); _case_tables_ready = 1; }
}

const unsigned short int **__ctype_b_loc(void) {
    return (const unsigned short int **)&_ctype_b_ptr;
}

int32_t **__ctype_toupper_loc(void) {
    _ensure_case_tables();
    static int32_t *p = NULL;
    p = &_ctype_toupper_tbl[128];
    return &p;
}

int32_t **__ctype_tolower_loc(void) {
    _ensure_case_tables();
    static int32_t *p = NULL;
    p = &_ctype_tolower_tbl[128];
    return &p;
}

// Real-time signal bounds: SIGRTMIN=34, SIGRTMAX=64 on Linux x86-64
int __libc_current_sigrtmin(void) { return 34; }
int __libc_current_sigrtmax(void) { return 64; }
