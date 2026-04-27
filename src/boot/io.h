#pragma once
#include <stdint.h>

static inline void outb(uint16_t port, uint8_t val) {
    __asm__ volatile ("outb %0, %1" :: "a"(val), "Nd"(port) : "memory");
}

static inline void outw(uint16_t port, uint16_t val) {
    __asm__ volatile ("outw %0, %1" :: "a"(val), "Nd"(port) : "memory");
}

static inline void outl(uint16_t port, uint32_t val) {
    __asm__ volatile ("outl %0, %1" :: "a"(val), "Nd"(port) : "memory");
}

static inline uint8_t inb(uint16_t port) {
    uint8_t val;
    __asm__ volatile ("inb %1, %0" : "=a"(val) : "Nd"(port) : "memory");
    return val;
}

static inline uint16_t inw(uint16_t port) {
    uint16_t val;
    __asm__ volatile ("inw %1, %0" : "=a"(val) : "Nd"(port) : "memory");
    return val;
}

static inline uint32_t inl(uint16_t port) {
    uint32_t val;
    __asm__ volatile ("inl %1, %0" : "=a"(val) : "Nd"(port) : "memory");
    return val;
}

static inline uint64_t read_cr2(void) {
    uint64_t val;
    __asm__ volatile ("mov %%cr2, %0" : "=r"(val));
    return val;
}

static inline uint64_t read_cr3(void) {
    uint64_t val;
    __asm__ volatile ("mov %%cr3, %0" : "=r"(val));
    return val;
}

static inline void write_cr3(uint64_t val) {
    __asm__ volatile ("mov %0, %%cr3" :: "r"(val) : "memory");
}

// Memory-mapped I/O — volatile prevents compiler reordering
static inline uint8_t  mmio_read8 (uintptr_t addr) { return *(volatile uint8_t  *)addr; }
static inline uint16_t mmio_read16(uintptr_t addr) { return *(volatile uint16_t *)addr; }
static inline uint32_t mmio_read32(uintptr_t addr) { return *(volatile uint32_t *)addr; }
static inline uint64_t mmio_read64(uintptr_t addr) { return *(volatile uint64_t *)addr; }

static inline void mmio_write8 (uintptr_t addr, uint8_t  v) { *(volatile uint8_t  *)addr = v; }
static inline void mmio_write16(uintptr_t addr, uint16_t v) { *(volatile uint16_t *)addr = v; }
static inline void mmio_write32(uintptr_t addr, uint32_t v) { *(volatile uint32_t *)addr = v; }
static inline void mmio_write64(uintptr_t addr, uint64_t v) { *(volatile uint64_t *)addr = v; }
