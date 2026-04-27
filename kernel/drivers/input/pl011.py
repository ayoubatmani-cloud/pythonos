"""
kernel.drivers.input.pl011 — PL011 UART serial input driver (arm64).

Provides an async read_char() that polls the PL011 receive FIFO.
Used as the keyboard replacement on arm64 QEMU virt — the shell calls
read_char() the same way it calls keyboard.read_char() on x86.

PL011 on QEMU virt (0x09000000):
  DR   0x09000000  data register (read = RX char, bits [7:0])
  FR   0x09000018  flag register  bit 4 = RXFE (RX FIFO empty)
"""

import asyncio
import _hal

_PL011_BASE = 0x09000000
_DR   = _PL011_BASE + 0x000   # data register
_FR   = _PL011_BASE + 0x018   # flag register
_RXFE = 1 << 4                 # RX FIFO empty flag


async def read_char() -> str:
    """Wait for the next character from the PL011 UART and return it."""
    while True:
        if not (_hal.mmio_read32(_FR) & _RXFE):
            ch = chr(_hal.mmio_read32(_DR) & 0xFF)
            return '\n' if ch == '\r' else ch
        await asyncio.sleep(0)
