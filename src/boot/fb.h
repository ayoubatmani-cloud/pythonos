#pragma once
#include <stdint.h>

typedef struct {
    uint64_t phys_addr;
    uint32_t pitch;     // bytes per row
    uint32_t width;
    uint32_t height;
    uint8_t  bpp;       // bits per pixel (expect 32)
    uint8_t  type;      // 1 = RGB linear, 2 = EGA text
    uint8_t  valid;
} framebuffer_info_t;

// Populated by parse_mb2_framebuffer(); read by python_kernel_start()
extern framebuffer_info_t boot_fb;

void parse_mb2_framebuffer(void *mb2_info);
