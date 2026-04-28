"""
kernel.log — Early boot serial logging + panic.

Before the framebuffer is up, everything goes to COM1 (x86_64) or PL011
(arm64) via the HAL.
After framebuffer init, log() is redirected to both.
"""

import _hal   # direct C extension — no circular import risk

_PREFIX = "[PythonOS] "
_ARCH = getattr(_hal, 'ARCH', 'x86_64')
_SERIAL_WIDTH = 80
_serial_col = 0

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

    def _putc(byte: int) -> None:
        while (_hal.mmio_read32(_SERIAL_FR) & _SERIAL_TXFF) != 0:
            pass
        _hal.mmio_write8(_SERIAL_DATA, byte & 0xFF)

else:
    _SERIAL_DATA = 0x3F8
    _SERIAL_LSR  = 0x3F8 + 5

    def _putc(byte: int) -> None:
        while (_hal.inb(_SERIAL_LSR) & 0x20) == 0:
            pass
        _hal.outb(_SERIAL_DATA, byte & 0xFF)


def _serial(line: str) -> None:
    """Output a log line followed by \\r\\n (for structured log messages)."""
    _serial_raw(line)
    _serial_newline()


def _serial_raw(text: str) -> None:
    """Output text to serial, translating \\n and wrapping at 80 columns."""
    global _serial_col
    for ch in text:
        if ch == '\n':
            _serial_newline()
            continue
        if ch == '\r':
            _putc(0x0D)
            _serial_col = 0
            continue
        if ch == '\b':
            _putc(0x08)
            if _serial_col > 0:
                _serial_col -= 1
            continue

        if _SERIAL_WIDTH > 0 and _serial_col >= _SERIAL_WIDTH:
            _serial_newline()

        _putc(ord(ch))
        if ch == '\t':
            _serial_col += 4 - (_serial_col % 4)
        elif ord(ch) >= 0x20:
            _serial_col += 1


def _serial_newline() -> None:
    global _serial_col
    _putc(0x0D)
    _putc(0x0A)
    _serial_col = 0
