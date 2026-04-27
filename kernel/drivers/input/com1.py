"""
kernel.drivers.input.com1 — COM1 serial input driver (x86_64 headless).

With QEMU -nographic -serial mon:stdio, user keystrokes reach COM1 (0x3F8),
not PS/2.  Polls the 16550A LSR Data Ready bit.

16550A COM1 registers (I/O port base 0x3F8):
  0x3F8  RBR  Receive Buffer Register (read, DLAB=0)
  0x3FD  LSR  Line Status Register    bit 0 = DR (Data Ready)
"""

import asyncio
from kernel.hal.io import inb

_COM1_RBR = 0x3F8
_COM1_LSR = 0x3FD


async def read_char() -> str:
    """Wait for the next character from COM1 and return it."""
    while True:
        if inb(_COM1_LSR) & 0x01:
            ch = chr(inb(_COM1_RBR) & 0x7F)
            return '\n' if ch == '\r' else ch
        await asyncio.sleep(0.005)
