"""
kernel.log — Early boot serial logging + panic.

Before the framebuffer is up, everything goes to COM1 (x86_64) or PL011
(arm64) via the HAL.
After framebuffer init, log() is redirected to both.
"""

import _hal   # direct C extension — no circular import risk

_PREFIX = "[PythonOS] "
_ARCH = getattr(_hal, 'ARCH', 'x86_64')

def info(msg: str) -> None:
    _serial(f"{_PREFIX}INFO  {msg}")

def warn(msg: str) -> None:
    _serial(f"{_PREFIX}WARN  {msg}")

def error(msg: str) -> None:
    _serial(f"{_PREFIX}ERROR {msg}")

def panic(msg: str) -> None:
    _serial(f"{_PREFIX}PANIC {msg}")
    # Halt all CPUs
    import ctypes
    while True:
        pass  # replaced by asm("cli; hlt") once we have ctypes MMIO


if _ARCH == 'arm64':
    _SERIAL_DATA = 0x09000000   # PL011 DR
    _SERIAL_FR   = 0x09000018   # PL011 FR
    _SERIAL_TXFF = 1 << 5       # TX FIFO full bit

    def _serial(line: str) -> None:
        for ch in (line + "\r\n"):
            while (_hal.mmio_read32(_SERIAL_FR) & _SERIAL_TXFF) != 0:
                pass
            _hal.mmio_write8(_SERIAL_DATA, ord(ch) & 0xFF)
else:
    _SERIAL_DATA = 0x3F8
    _SERIAL_LSR  = 0x3F8 + 5

    def _serial(line: str) -> None:
        for ch in (line + "\r\n"):
            # Wait for transmit holding register empty
            while (_hal.inb(_SERIAL_LSR) & 0x20) == 0:
                pass
            _hal.outb(_SERIAL_DATA, ord(ch) & 0xFF)
