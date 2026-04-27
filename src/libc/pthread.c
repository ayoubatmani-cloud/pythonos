/*
 * pthread.c — Minimal pthread stubs for single-core CPython.
 *
 * CPython WITH_THREAD uses pthreads for:
 *   - The GIL (mutex + condvar)
 *   - Thread-local storage (pthread_key_*)
 *   - Thread creation (_threadmodule.c — optional, we stub it to fail)
 *
 * On a single core with cooperative scheduling (asyncio), mutex lock/unlock
 * are no-ops — only one Python thread runs at a time.
 * Thread-local storage is emulated with a small fixed table (CPython only
 * creates a handful of keys).
 */

#include "include/libc.h"
#include <stdint.h>

// Types and macros are declared in include/libc.h

// ── Thread-local storage emulation ───────────────────────────────────────────

#define MAX_KEYS 64
#define MAX_THREADS 1   // single-core v1

static struct {
    int   in_use;
    void (*destructor)(void *);
} _tsd_keys[MAX_KEYS];

static void *_tsd_values[MAX_KEYS];  // single thread, so one set of values

pthread_key_t _tsd_next_key = 0;

int pthread_key_create(pthread_key_t *key, void (*destructor)(void *)) {
    for (unsigned k = 0; k < MAX_KEYS; k++) {
        if (!_tsd_keys[k].in_use) {
            _tsd_keys[k].in_use     = 1;
            _tsd_keys[k].destructor = destructor;
            _tsd_values[k]          = NULL;
            *key = k;
            return 0;
        }
    }
    return ENOMEM;
}

int pthread_key_delete(pthread_key_t key) {
    if (key >= MAX_KEYS) return EINVAL;
    _tsd_keys[key].in_use = 0;
    _tsd_values[key] = NULL;
    return 0;
}

void *pthread_getspecific(pthread_key_t key) {
    if (key >= MAX_KEYS || !_tsd_keys[key].in_use) return NULL;
    return _tsd_values[key];
}

int pthread_setspecific(pthread_key_t key, const void *val) {
    if (key >= MAX_KEYS || !_tsd_keys[key].in_use) return EINVAL;
    _tsd_values[key] = (void *)val;
    return 0;
}

// ── Thread identity ───────────────────────────────────────────────────────────

pthread_t pthread_self(void) { return 1; }

int pthread_equal(pthread_t a, pthread_t b) { return a == b; }

// ── Thread creation (stub — fails gracefully) ─────────────────────────────────
// CPython's _thread module calls this. Returning ENOSYS causes _thread to
// raise RuntimeError, which is acceptable until we implement real threading.

int pthread_create(pthread_t *tid, const pthread_attr_t *attr,
                   void *(*fn)(void *), void *arg) {
    (void)tid; (void)attr; (void)fn; (void)arg;
    return ENOSYS;
}

int pthread_join(pthread_t tid, void **retval) {
    (void)tid; (void)retval;
    return EINVAL;
}

int pthread_detach(pthread_t tid) { (void)tid; return 0; }

// ── Attributes (all no-ops) ───────────────────────────────────────────────────

int pthread_attr_init(pthread_attr_t *a)    { (void)a; return 0; }
int pthread_attr_destroy(pthread_attr_t *a) { (void)a; return 0; }
int pthread_attr_setstacksize(pthread_attr_t *a, size_t s) { (void)a; (void)s; return 0; }
int pthread_attr_getstacksize(pthread_attr_t *a, size_t *s) { (void)a; *s = 65536; return 0; }
int pthread_attr_setdetachstate(pthread_attr_t *a, int s) { (void)a; (void)s; return 0; }

// ── Mutexes (single-core — lock is always available, no preemption) ───────────

int pthread_mutex_init(pthread_mutex_t *m, const pthread_mutexattr_t *a) {
    (void)a; m->locked = 0; return 0;
}
int pthread_mutex_destroy(pthread_mutex_t *m) { (void)m; return 0; }
int pthread_mutex_lock(pthread_mutex_t *m)    { m->locked = 1; return 0; }
int pthread_mutex_trylock(pthread_mutex_t *m) { m->locked = 1; return 0; }
int pthread_mutex_unlock(pthread_mutex_t *m)  { m->locked = 0; return 0; }

int pthread_mutexattr_init(pthread_mutexattr_t *a)    { (void)a; return 0; }
int pthread_mutexattr_destroy(pthread_mutexattr_t *a) { (void)a; return 0; }
int pthread_mutexattr_settype(pthread_mutexattr_t *a, int t) { (void)a; (void)t; return 0; }

// ── Condition variables ───────────────────────────────────────────────────────
// Single-core: wait just returns immediately (no other thread will signal).
// CPython uses condvars for the GIL; since we never block, this is fine.

int pthread_cond_init(pthread_cond_t *c, const pthread_condattr_t *a) {
    (void)a; c->seq = 0; return 0;
}
int pthread_cond_destroy(pthread_cond_t *c)         { (void)c; return 0; }
int pthread_cond_signal(pthread_cond_t *c)          { c->seq++; return 0; }
int pthread_cond_broadcast(pthread_cond_t *c)       { c->seq++; return 0; }
int pthread_cond_wait(pthread_cond_t *c, pthread_mutex_t *m) {
    (void)c; (void)m; return 0;  // single-core: no actual waiting needed
}
int pthread_cond_timedwait(pthread_cond_t *c, pthread_mutex_t *m,
                           const struct timespec *t) {
    (void)c; (void)m; (void)t; return 0;
}

int pthread_condattr_init(pthread_condattr_t *a)    { (void)a; return 0; }
int pthread_condattr_destroy(pthread_condattr_t *a) { (void)a; return 0; }
int pthread_condattr_setclock(pthread_condattr_t *a, clockid_t c) { (void)a; (void)c; return 0; }

// ── Read-write locks ──────────────────────────────────────────────────────────

int pthread_rwlock_init(pthread_rwlock_t *l, const pthread_rwlockattr_t *a) { (void)l; (void)a; return 0; }
int pthread_rwlock_destroy(pthread_rwlock_t *l)  { (void)l; return 0; }
int pthread_rwlock_rdlock(pthread_rwlock_t *l)   { (void)l; return 0; }
int pthread_rwlock_wrlock(pthread_rwlock_t *l)   { (void)l; return 0; }
int pthread_rwlock_tryrdlock(pthread_rwlock_t *l){ (void)l; return 0; }
int pthread_rwlock_trywrlock(pthread_rwlock_t *l){ (void)l; return 0; }
int pthread_rwlock_unlock(pthread_rwlock_t *l)   { (void)l; return 0; }

// ── pthread_once ──────────────────────────────────────────────────────────────

int pthread_once(pthread_once_t *once, void (*fn)(void)) {
    if (!*once) { *once = 1; fn(); }
    return 0;
}

// ── Cancellation (stub) ───────────────────────────────────────────────────────

int pthread_setcancelstate(int state, int *old)  { (void)state; if (old) *old = 0; return 0; }
int pthread_setcanceltype(int type, int *old)    { (void)type;  if (old) *old = 0; return 0; }
int pthread_cancel(pthread_t tid)                { (void)tid; return 0; }
void pthread_testcancel(void)                    { }

void pthread_exit(void *retval) {
    (void)retval;
    // Single-core bare-metal: thread exit halts the system
    __asm__ volatile ("cli");
    for (;;) __asm__ volatile ("hlt");
}
