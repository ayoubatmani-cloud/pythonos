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


async def read_byte() -> int:
    """Wait for the next raw byte from COM1 (0–255, no translation)."""
    while True:
        if inb(_COM1_LSR) & 0x01:
            return inb(_COM1_RBR) & 0xFF
        await asyncio.sleep(0)


async def read_char() -> str:
    """Wait for the next character from COM1 and return it.

    Translates CR→LF for consumers (legacy line-buffered shell loops)
    that want to treat Enter as '\\n'. Use read_byte() for the raw
    stream that line editors (linenoise) need.
    """
    b = await read_byte()
    ch = chr(b & 0x7F)
    return '\n' if ch == '\r' else ch
