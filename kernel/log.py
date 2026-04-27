"""
kernel.log — Early boot serial logging + panic.

Before the framebuffer is up, everything goes to COM1 via the HAL.
After framebuffer init, log() is redirected to both.
"""

import _hal   # direct C extension — no circular import risk

_PREFIX = "[PythonOS] "

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

def _serial(line: str) -> None:
    COM1_DATA = 0x3F8
    COM1_LSR  = 0x3F8 + 5

    for ch in (line + "\r\n"):
        # Wait for transmit holding register empty
        while (_hal.inb(COM1_LSR) & 0x20) == 0:
            pass
        _hal.outb(COM1_DATA, ord(ch) & 0xFF)
