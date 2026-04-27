#pragma once
#include <stdint.h>

#define PIT_CHANNEL0  0x40
#define PIT_COMMAND   0x43
#define PIT_BASE_HZ   1193180

void pit_init(uint32_t hz);
