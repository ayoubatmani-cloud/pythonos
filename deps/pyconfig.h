/*
 * pyconfig.h — PythonOS bare-metal CPython configuration.
 *
 * Generated for: x86-64, no OS, GIL enabled, frozen modules only.
 * Target compiler: x86_64-elf-gcc (freestanding)
 *
 * Strategy:
 *   - Define HAVE_* only for features our libc actually provides.
 *   - Disable all POSIX optional features (fork, exec, sockets, etc.).
 *   - Use our libc.h as the system header set.
 */

#ifndef Py_PYCONFIG_H
#define Py_PYCONFIG_H

/* ── Byte order ─────────────────────────────────────────────────────────── */
/* WORDS_BIGENDIAN intentionally NOT defined — we are little-endian (x86-64).
 * dtoa.c uses #if defined(WORDS_BIGENDIAN), which would be true even with =0. */
/* PY_BIG_ENDIAN / PY_LITTLE_ENDIAN are set by pyport.h from WORDS_BIGENDIAN */

/* ── Platform word size ─────────────────────────────────────────────────── */
#define SIZEOF_INT          4
#define SIZEOF_LONG         8
#define SIZEOF_LONG_LONG    8
#define SIZEOF_SIZE_T       8
#define SIZEOF_VOID_P       8
#define SIZEOF_SHORT        2
#define SIZEOF_FLOAT        4
#define SIZEOF_DOUBLE       8
#define SIZEOF_FPOS_T       8
#define SIZEOF_OFF_T        8
#define SIZEOF_TIME_T       8
#define SIZEOF_UINTPTR_T    8
#define SIZEOF_PTHREAD_T    8    /* stubbed */
#define SIZEOF_WCHAR_T      4

/* ── Alignment ──────────────────────────────────────────────────────────── */
#define ALIGNOF_MAX_ALIGN_T  16
#define ALIGNOF_SIZE_T       8
#define ALIGNOF_LONG         8
#define PY_FORMAT_SIZE_T     "z"

/* ── Compiler / C standard ──────────────────────────────────────────────── */
#define HAVE_C99_BOOL 1
#define HAVE_LONG_LONG 1
#define HAVE_STDARG_PROTOTYPES 1
#define HAVE_DECL_ISNAN 1
#define HAVE_DECL_ISINF 1
#define HAVE_DECL_ISFINITE 1
#define HAVE_DECL_INFINITY 1
#define HAVE_DECL_NAN 1
#define PY_UINT32_T uint32_t
#define PY_UINT64_T uint64_t
#define PY_INT32_T  int32_t
#define PY_INT64_T  int64_t

/* ── Threading (GIL enabled, pthreads stubbed) ──────────────────────────── */
#define WITH_THREAD 1
#define _POSIX_THREADS 1
/* Our src/libc/include/pthread.h is on the include path; cpython/pythread.h
   checks HAVE_PTHREAD_H and then does #include <pthread.h> to get pthread_key_t */
#define HAVE_PTHREAD_H 1

/* ── Memory functions — all provided by src/libc/ ───────────────────────── */
#define HAVE_MMAP        1   /* redirected to malloc in syscalls.c */
/* HAVE_MREMAP not defined */
#define HAVE_MPROTECT    1
#define HAVE_GETTIMEOFDAY 1
#define HAVE_CLOCK       1
#define HAVE_CLOCK_GETTIME 1
#define HAVE_NANOSLEEP   1   /* nanosleep() stub in syscalls.c */
#define HAVE_GETPAGESIZE 1
/* HAVE_MALLOC_H not defined — #ifdef HAVE_MALLOC_H would try to include it */
/* HAVE_ALLOCA_H not defined */

/* ── String / character functions ───────────────────────────────────────── */
#define HAVE_MEMCPY      1
#define HAVE_MEMMOVE     1
#define HAVE_MEMSET      1
#define HAVE_MEMCHR      1
#define HAVE_STRCMP      1
#define HAVE_STRDUP      1
#define HAVE_STRNDUP     1
#define HAVE_STRCASECMP  1
#define HAVE_STRNCASECMP 1
#define HAVE_STRTOL      1
#define HAVE_STRTOLL     1
#define HAVE_STRTOUL     1
#define HAVE_STRTOULL    1
#define HAVE_STRTOD      1
/* HAVE_STRTOF not defined */
/* HAVE_STRTOLD not defined */

/* ── Math ───────────────────────────────────────────────────────────────── */
#define HAVE_HYPOT       1
#define HAVE_LOG2        1
/* HAVE_LOG1P not defined */
#define HAVE_ROUND       1
/* HAVE_TGAMMA not defined */
/* HAVE_LGAMMA not defined */
/* HAVE_ERF not defined */
/* HAVE_ERFC not defined */
/* HAVE_COPYSIGN not defined */
/* HAVE_NEXTAFTER not defined */
#define HAVE_ISINF       1
#define HAVE_ISNAN       1
/* HAVE_FINITE not defined */
#define X87_DOUBLE_ROUNDING 0

/* ── I/O (limited — frozen module imports don't need real file I/O) ─────── */
#define HAVE_UNISTD_H    1   /* our unistd.h stub: lseek/off_t/read/write */
#define HAVE_FCNTL_H     1   /* our fcntl.h stub: O_* flags, F_* cmds */
#define HAVE_SYS_STAT_H  1   /* our sys/stat.h stub provides struct stat */
/* HAVE_STAT not defined */
/* HAVE_FSTAT not defined */
/* HAVE_LSTAT not defined */
/* HAVE_ACCESS not defined */
/* HAVE_GETCWD not defined */
/* HAVE_CHDIR not defined */
/* HAVE_MKDIR not defined */
/* HAVE_RENAME not defined */
/* HAVE_UNLINK not defined */
/* HAVE_SYMLINK not defined */
/* HAVE_LINK not defined */
/* HAVE_OPENDIR not defined */
/* HAVE_READDIR_R not defined */
/* HAVE_GETDIRENTRIES not defined */

/* ── Processes — none ───────────────────────────────────────────────────── */
/* HAVE_FORK not defined */
/* HAVE_VFORK not defined */
/* HAVE_EXECV not defined */
/* HAVE_EXECVE not defined */
/* HAVE_SPAWNV not defined */
#define HAVE_GETPID      1   /* returns 1 */
/* HAVE_GETPPID not defined */
/* HAVE_GETPGRP not defined */
/* HAVE_SETPGID not defined */
/* HAVE_SETSID not defined */
/* HAVE_WAITPID not defined */
/* HAVE_WAIT3 not defined */
/* HAVE_WAIT4 not defined */

/* ── Signals — minimal stubs ─────────────────────────────────────────────── */
/* HAVE_SIGNAL_H not defined — #ifdef HAVE_SIGNAL_H would try to include <signal.h> */
/* HAVE_SIGACTION not defined — #ifdef HAVE_SIGACTION guards struct sigaction usage */
/* HAVE_SIGINTERRUPT not defined */
/* HAVE_SIGPENDING not defined */
#define HAVE_SIGPROCMASK 1   /* stubbed — sigemptyset/sigfillset/sigprocmask */
/* HAVE_SIGWAIT not defined */

/* ── Networking — none ──────────────────────────────────────────────────── */
/* HAVE_SOCKET not defined */
/* HAVE_SOCKETPAIR not defined */
/* HAVE_GETADDRINFO not defined */
/* HAVE_INET_ATON not defined */
/* HAVE_INET_NTOA not defined */
#define ENABLE_IPV6      0

/* ── Pseudo-terminals / TTY — none ─────────────────────────────────────── */
/* HAVE_OPENPTY not defined */
/* HAVE_FORKPTY not defined */
/* HAVE_TERMIOS_H not defined */
/* HAVE_PTY_H not defined */

/* ── Dynamic loading ────────────────────────────────────────────────────── */
/* All modules compiled-in; no shared libraries on bare metal.
 * HAVE_DYNAMIC_LOADING must be set so importdl.c compiles the extension-module
 * loader infrastructure (_Py_ext_module_loader_*, _PyImport_RunModInitFunc)
 * which is used even for statically-linked builtin modules in CPython 3.14. */
#define HAVE_DYNAMIC_LOADING 1
#define HAVE_DLOPEN      1   /* enables _PyImport_GetDLOpenFlags and dynload_shlib.c */
#define HAVE_DLFCN_H     1   /* our dlfcn.h stub: dlopen/dlsym/dlclose return NULL */
#define Py_ENABLE_SHARED 0
#define WITH_DYLD        0
#define SOABI            ""

/* ── Locale ─────────────────────────────────────────────────────────────── */
#define HAVE_SETLOCALE   1
#define HAVE_LOCALECONV  1
#define HAVE_LANGINFO_H  1   /* our langinfo.h stub: nl_langinfo returns "" */
#define HAVE_NL_LANGINFO 1   /* nl_langinfo() stub in syscalls.c */
#define PY_COERCE_C_LOCALE 0

/* ── Random ─────────────────────────────────────────────────────────────── */
#define HAVE_GETRANDOM    1   /* our PRNG in syscalls.c */
#define HAVE_SYS_RANDOM_H 1   /* our sys/random.h stub: GRND_NONBLOCK + getrandom() */
/* HAVE_GETENTROPY not defined */
/* HAVE_DEV_URANDOM not defined */

/* ── Compile-time Python flags ──────────────────────────────────────────── */
#define Py_BUILD_CORE 1
#define Py_ENABLE_SHARED 0
#define Py_NO_ENABLE_SHARED 1
#define PYTHONPATH ""
#define PREFIX     ""
#define EXEC_PREFIX ""
#define VERSION    "3.14"
#define VPATH      ""
#define _PYTHONFRAMEWORK ""

/* Enable the GIL (we're not using free-threading in v1 — simpler) */
#undef  Py_GIL_DISABLED

/* Disable site.py (no filesystem) — use #if not #ifdef */
/* HAVE_SITE not defined */

/* Disable readline — not defined, not available */
/* HAVE_READLINE not defined */
/* HAVE_RL_CALLBACK_HANDLER_INSTALL not defined */
/* HAVE_RL_COMPLETION_SUPPRESS_APPEND not defined */

/* ── pymalloc ────────────────────────────────────────────────────────────── */
/* Use CPython's object allocator (pymalloc) on top of our malloc */
#define WITH_PYMALLOC 1
#define PYMALLOC_DEBUG 0

/* ── Debugging ───────────────────────────────────────────────────────────── */
/* Py_DEBUG not defined (0) */
#define NDEBUG   1

/* ── Assertions ──────────────────────────────────────────────────────────── */
#ifdef NDEBUG
#  define assert(x) ((void)0)
#else
#  define assert(x) do { if (!(x)) abort(); } while (0)
#endif

/* ── va_list ─────────────────────────────────────────────────────────────── */
#define HAVE_VA_COPY 1
#define VA_LIST_IS_ARRAY 0

/* ── Misc CPython build knobs ────────────────────────────────────────────── */
#define DOUBLE_IS_LITTLE_ENDIAN_IEEE754 1
#define FLOAT_IS_LITTLE_ENDIAN_IEEE754  1
/* PY_UNICODE_TYPE and Py_UNICODE_SIZE are defined by CPython headers in 3.14;
   do NOT redefine them here (PY_UNICODE_TYPE is deprecated typedef to wchar_t) */
#define HAVE_WCHAR_H     1   /* wchar_t is provided by GCC freestanding headers */
/* HAVE_WCSCOLL not defined */
/* HAVE_WCSXFRM not defined */
#define HAVE_USABLE_WCHAR_T 1

/* We don't have /proc or /dev — tell CPython not to look */
/* HAVE_PROC_PIDPATH not defined */
/* HAVE_SYS_SYSCALL_H not defined */
/* HAVE_SYS_IOCTL_H not defined */
/* HAVE_SYS_PARAM_H not defined */
/* HAVE_SYS_RESOURCE_H not defined */

/* Compiler builtins available in GCC/Clang freestanding */
/* HAVE___THREAD not defined */
#define HAVE_GCC_ASM_FOR_X87 1
#define HAVE_GCC_UINT128_T   1

/* Do NOT define _GNU_SOURCE or _POSIX_C_SOURCE here.
 * Those macros cause system headers (time.h, stdlib.h) to transitively
 * include bits/pthreadtypes.h, which defines real Linux pthread struct layouts
 * that conflict with our single-core stub definitions in pthread.h. */

#endif /* Py_PYCONFIG_H */
