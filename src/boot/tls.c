#include "tls.h"

#define IA32_FS_BASE 0xC0000100U

extern uint8_t __tls_start[];
extern uint8_t __tdata_start[];
extern uint8_t __tdata_end[];
extern uint8_t __tls_end[];

static void wrmsr(uint32_t msr, uint64_t value) {
    __asm__ volatile("wrmsr"
                     :
                     : "c"(msr), "a"((uint32_t)value), "d"((uint32_t)(value >> 32))
                     : "memory");
}

static uintptr_t align_up(uintptr_t value, uintptr_t alignment) {
    return (value + alignment - 1U) & ~(alignment - 1U);
}

int tls_init_area(uint8_t *area, size_t area_size) {
    uintptr_t area_start = align_up((uintptr_t)area, 16U);
    size_t prefix = area_start - (uintptr_t)area;
    if (prefix >= area_size) {
        return 0;
    }

    uint8_t *block = (uint8_t *)area_start;
    size_t usable_size = area_size - prefix;
    size_t tdata_size = (size_t)(__tdata_end - __tdata_start);
    size_t tls_size = (size_t)(__tls_end - __tls_start);

    if (tdata_size > tls_size || tls_size + sizeof(uint64_t) > usable_size) {
        return 0;
    }

    for (size_t i = 0; i < usable_size; i++) {
        block[i] = 0;
    }
    for (size_t i = 0; i < tdata_size; i++) {
        block[i] = __tdata_start[i];
    }

    uintptr_t fs_base = (uintptr_t)block + tls_size;
    *(uint64_t *)fs_base = fs_base;
    wrmsr(IA32_FS_BASE, fs_base);
    return 1;
}
