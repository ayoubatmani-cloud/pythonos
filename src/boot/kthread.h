#ifndef PYTHONOS_BOOT_KTHREAD_H
#define PYTHONOS_BOOT_KTHREAD_H

typedef void (*kthread_entry_t)(void *);

// Cooperative native kernel threads on the bootstrap CPU.
// AP startup and preemptive timer scheduling are separate layers.
void kthread_init(void);
int kthread_create(kthread_entry_t entry, void *arg, const char *name);
void kthread_yield(void);
int kthread_is_zombie(int id);
int kthread_selftest(void);

#endif
