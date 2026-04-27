"""
kernel.hal.io — Thin Python wrapper over the _hal C extension.

Everything here is a direct hardware call. No buffering, no policy.
Upper layers own the policy.
"""

import _hal

# Port I/O
inb  = _hal.inb
inw  = _hal.inw
inl  = _hal.inl
outb = _hal.outb
outw = _hal.outw
outl = _hal.outl

# Control registers
read_cr2  = _hal.read_cr2
read_cr3  = _hal.read_cr3
write_cr3 = _hal.write_cr3

# MMIO
mmio_read8   = _hal.mmio_read8
mmio_read32  = _hal.mmio_read32
mmio_write32 = _hal.mmio_write32


def set_interrupt_router(fn) -> None:
    """Register the callable that all hardware/software interrupts route through."""
    _hal.set_interrupt_router(fn)
