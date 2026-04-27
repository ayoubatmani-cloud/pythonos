/* sys/syscall.h — bare-metal stub for PythonOS.
 * CPython's thread_pthread.h uses syscall(SYS_gettid) on Linux targets.
 * We stub syscall to return 1 (the kernel thread ID).
 */
#pragma once
#include <stdarg.h>

#define SYS_gettid 186

long syscall(long number, ...);
