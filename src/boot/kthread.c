#include <stdint.h>
#include <stddef.h>
#include "kthread.h"

#define KTHREAD_MAX 8
#define KTHREAD_STACK_SIZE (64U * 1024U)
#define KTHREAD_SELFTEST_ITERS 7

typedef enum {
    KTHREAD_UNUSED = 0,
    KTHREAD_RUNNABLE,
    KTHREAD_RUNNING,
    KTHREAD_ZOMBIE,
} kthread_state_t;

typedef struct {
    int id;
    uint64_t *rsp;
    kthread_state_t state;
    kthread_entry_t entry;
    void *arg;
    const char *name;
    uint8_t stack[KTHREAD_STACK_SIZE] __attribute__((aligned(16)));
} kthread_t;

extern void kthread_switch(uint64_t **old_rsp, uint64_t *new_rsp);

static kthread_t threads[KTHREAD_MAX];
static kthread_t *current_thread;
static int initialized;

static void kthread_trampoline(void) __attribute__((noreturn));

static uint64_t *kthread_make_stack(kthread_t *thread) {
    uintptr_t top = (uintptr_t)thread->stack + KTHREAD_STACK_SIZE;
    top &= ~(uintptr_t)0xFUL;
    top -= 8;  // SysV ABI: functions enter with RSP % 16 == 8.

    uint64_t *sp = (uint64_t *)top;
    *--sp = (uint64_t)(uintptr_t)kthread_trampoline;
    *--sp = 0;  // rbp
    *--sp = 0;  // rbx
    *--sp = 0;  // r12
    *--sp = 0;  // r13
    *--sp = 0;  // r14
    *--sp = 0;  // r15
    return sp;
}

void kthread_init(void) {
    if (initialized) {
        return;
    }

    for (int i = 0; i < KTHREAD_MAX; i++) {
        threads[i].id = i;
        threads[i].rsp = NULL;
        threads[i].state = KTHREAD_UNUSED;
        threads[i].entry = NULL;
        threads[i].arg = NULL;
        threads[i].name = NULL;
    }

    threads[0].state = KTHREAD_RUNNING;
    threads[0].name = "boot";
    current_thread = &threads[0];
    initialized = 1;
}

int kthread_create(kthread_entry_t entry, void *arg, const char *name) {
    if (!entry) {
        return -1;
    }
    if (!initialized) {
        kthread_init();
    }

    for (int i = 1; i < KTHREAD_MAX; i++) {
        kthread_t *thread = &threads[i];
        if (thread->state == KTHREAD_UNUSED || thread->state == KTHREAD_ZOMBIE) {
            thread->entry = entry;
            thread->arg = arg;
            thread->name = name;
            thread->rsp = kthread_make_stack(thread);
            thread->state = KTHREAD_RUNNABLE;
            return thread->id;
        }
    }

    return -1;
}

static kthread_t *kthread_pick_next(void) {
    if (!current_thread) {
        return NULL;
    }

    int start = current_thread->id;
    for (int offset = 1; offset <= KTHREAD_MAX; offset++) {
        int index = (start + offset) % KTHREAD_MAX;
        if (threads[index].state == KTHREAD_RUNNABLE) {
            return &threads[index];
        }
    }

    return current_thread;
}

void kthread_yield(void) {
    if (!initialized || !current_thread) {
        return;
    }

    kthread_t *previous = current_thread;
    kthread_t *next = kthread_pick_next();
    if (!next || next == previous) {
        return;
    }

    if (previous->state == KTHREAD_RUNNING) {
        previous->state = KTHREAD_RUNNABLE;
    }
    next->state = KTHREAD_RUNNING;
    current_thread = next;

    kthread_switch(&previous->rsp, next->rsp);
}

int kthread_is_zombie(int id) {
    if (id < 0 || id >= KTHREAD_MAX) {
        return 0;
    }
    return threads[id].state == KTHREAD_ZOMBIE;
}

static void kthread_trampoline(void) {
    kthread_t *thread = current_thread;
    if (thread && thread->entry) {
        thread->entry(thread->arg);
    }
    if (thread) {
        thread->state = KTHREAD_ZOMBIE;
    }
    for (;;) {
        kthread_yield();
    }
}

static volatile uint32_t selftest_a;
static volatile uint32_t selftest_b;

static void selftest_worker(void *arg) {
    volatile uint32_t *counter = (volatile uint32_t *)arg;
    for (uint32_t i = 0; i < KTHREAD_SELFTEST_ITERS; i++) {
        (*counter)++;
        kthread_yield();
    }
}

int kthread_selftest(void) {
    kthread_init();

    selftest_a = 0;
    selftest_b = 0;

    int a = kthread_create(selftest_worker, (void *)&selftest_a, "selftest-a");
    int b = kthread_create(selftest_worker, (void *)&selftest_b, "selftest-b");
    if (a < 0 || b < 0) {
        return 0;
    }

    for (uint32_t spins = 0; spins < 128; spins++) {
        if (kthread_is_zombie(a) && kthread_is_zombie(b)) {
            break;
        }
        kthread_yield();
    }

    return selftest_a == KTHREAD_SELFTEST_ITERS &&
           selftest_b == KTHREAD_SELFTEST_ITERS &&
           kthread_is_zombie(a) &&
           kthread_is_zombie(b);
}
