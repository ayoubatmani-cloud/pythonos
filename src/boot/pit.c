#include "pit.h"
#include "io.h"

void pit_init(uint32_t hz) {
    uint32_t divisor = PIT_BASE_HZ / hz;
    // Channel 0, lo/hi byte access, mode 2 (rate generator)
    outb(PIT_COMMAND, 0x34);
    outb(PIT_CHANNEL0, (uint8_t)(divisor & 0xFF));
    outb(PIT_CHANNEL0, (uint8_t)(divisor >> 8));
}
