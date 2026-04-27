#include "fb.h"
#include <stdint.h>
#include <stddef.h>

framebuffer_info_t boot_fb = {0};

typedef struct { uint32_t type; uint32_t size; } mb2_tag_t;

typedef struct {
    uint32_t type;          // = 8
    uint32_t size;
    uint64_t framebuffer_addr;
    uint32_t framebuffer_pitch;
    uint32_t framebuffer_width;
    uint32_t framebuffer_height;
    uint8_t  framebuffer_bpp;
    uint8_t  framebuffer_type;
    uint16_t reserved;
} __attribute__((packed)) mb2_fb_tag_t;

void parse_mb2_framebuffer(void *mb2_info) {
    uint32_t total_size = *(uint32_t *)mb2_info;
    uint8_t *ptr = (uint8_t *)mb2_info + 8;
    uint8_t *end = (uint8_t *)mb2_info + total_size;

    while (ptr < end) {
        mb2_tag_t *tag = (mb2_tag_t *)ptr;
        if (tag->type == 0) break;

        if (tag->type == 8) {
            mb2_fb_tag_t *fb = (mb2_fb_tag_t *)tag;
            boot_fb.phys_addr = fb->framebuffer_addr;
            boot_fb.pitch     = fb->framebuffer_pitch;
            boot_fb.width     = fb->framebuffer_width;
            boot_fb.height    = fb->framebuffer_height;
            boot_fb.bpp       = fb->framebuffer_bpp;
            boot_fb.type      = fb->framebuffer_type;
            boot_fb.valid     = 1;
            return;
        }

        ptr += (tag->size + 7) & ~7;
    }
}
