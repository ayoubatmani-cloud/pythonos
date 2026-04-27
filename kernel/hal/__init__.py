from kernel.hal.io import (
    inb, inw, inl, outb, outw, outl,
    read_cr2, read_cr3, write_cr3,
    mmio_read8, mmio_read32, mmio_write32,
    set_interrupt_router,
)
