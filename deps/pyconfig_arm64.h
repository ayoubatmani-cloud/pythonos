/*
 * pyconfig.h — PythonOS bare-metal CPython configuration.
 *
 * Generated for: AArch64, no OS, GIL enabled, frozen modules only.
 * Target compiler: aarch64-elf-gcc (freestanding)
 */

#ifndef Py_PYCONFIG_H
#define Py_PYCONFIG_H

/* ── Byte order ─────────────────────────────────────────────────────────── */
/* WORDS_BIGENDIAN intentionally NOT defined — AArch64 in LE mode */

/* ── Platform word size ─────────────────────────────────────────────────── */
#define SIZEOF_INT          4
#define SIZEOF_LONG         8
#define SIZEOF_LONG_LONG    8
#define SIZEOF_SIZE_T       8
#define SIZEOF_VOID_P       8
#define SIZEOF_SHORT        2
#define SIZEOF_FLOAT        4
#define SIZEOF_DOUBLE       8
#define SIZEOF_LONG_DOUBLE  16   /* AArch64: 128-bit quad precision */
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
#define HAVE_PTHREAD_H 1

/* ── Memory functions — all provided by src/libc/ ───────────────────────── */
#define HAVE_MMAP        1
#define HAVE_MPROTECT    1
#define HAVE_GETTIMEOFDAY 1
#define HAVE_CLOCK       1
#define HAVE_CLOCK_GETTIME 1
#define HAVE_NANOSLEEP   1
#define HAVE_GETPAGESIZE 1

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

/* ── Math ───────────────────────────────────────────────────────────────── */
#define HAVE_HYPOT       1
#define HAVE_LOG2        1
#define HAVE_ROUND       1
#define HAVE_ISINF       1
#define HAVE_ISNAN       1
/* X87_DOUBLE_ROUNDING intentionally NOT defined — AArch64 has no x87 FPU */

/* ── I/O (limited — frozen module imports don't need real file I/O) ─────── */
#define HAVE_UNISTD_H    1
#define HAVE_FCNTL_H     1
#define HAVE_SYS_STAT_H  1
#define HAVE_DIRENT_H    1
#define HAVE_UTIME_H     1
#define HAVE_SYS_TIMES_H 1

/* ── Processes — none ───────────────────────────────────────────────────── */
#define HAVE_GETPID      1

/* ── Signals — minimal stubs ─────────────────────────────────────────────── */
#define HAVE_SIGPROCMASK 1

/* ── Networking — none ──────────────────────────────────────────────────── */
#define ENABLE_IPV6      0

/* ── Dynamic loading ────────────────────────────────────────────────────── */
#define HAVE_DYNAMIC_LOADING 1
#define HAVE_DLOPEN      1
#define HAVE_DLFCN_H     1
#define Py_ENABLE_SHARED 0
#define WITH_DYLD        0
#define SOABI            ""

/* ── Locale ─────────────────────────────────────────────────────────────── */
#define HAVE_SETLOCALE   1
#define HAVE_LOCALECONV  1
#define HAVE_LANGINFO_H  1
#define HAVE_NL_LANGINFO 1
#define PY_COERCE_C_LOCALE 0

/* ── Random ─────────────────────────────────────────────────────────────── */
#define HAVE_GETRANDOM    1
#define HAVE_SYS_RANDOM_H 1

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

/* Enable the GIL */
#undef  Py_GIL_DISABLED

/* ── pymalloc ────────────────────────────────────────────────────────────── */
#define WITH_PYMALLOC 1
#define PYMALLOC_DEBUG 0

/* ── Debugging ───────────────────────────────────────────────────────────── */
#define NDEBUG   1

/* ── Assertions ──────────────────────────────────────────────────────────── */
#ifdef NDEBUG
#  define assert(x) ((void)0)
#else
#  define assert(x) do { if (!(x)) abort(); } while (0)
#endif

/* ── va_list ─────────────────────────────────────────────────────────────── */
/* On AArch64, __builtin_va_list is struct __va_list_tag[1] — an array type.
 * Setting VA_LIST_IS_ARRAY=1 tells CPython to treat va_list as a pointer
 * when passing to helper functions (va_list * instead of va_list). */
#define HAVE_VA_COPY 1
#define VA_LIST_IS_ARRAY 1

/* ── Misc CPython build knobs ────────────────────────────────────────────── */
#define DOUBLE_IS_LITTLE_ENDIAN_IEEE754 1
#define FLOAT_IS_LITTLE_ENDIAN_IEEE754  1
#define HAVE_WCHAR_H     1
#define HAVE_USABLE_WCHAR_T 1

/* AArch64-specific: no x87 FPU, 128-bit ints available */
#undef  HAVE_GCC_ASM_FOR_X87
#define HAVE_GCC_UINT128_T   1

/* Do NOT define _GNU_SOURCE or _POSIX_C_SOURCE here. */

#endif /* Py_PYCONFIG_H */
