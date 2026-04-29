"""
kernel.interrupts.router — Interrupt dispatch table.

The C HAL calls _dispatch() on every interrupt/exception.
Python handlers register via @interrupt(vector) or router.register(vector).

Async handlers are scheduled on the kernel event loop (set by the scheduler).
Sync handlers run inline — reserve these for latency-critical IRQs like
the PIT timer tick.
"""


import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable

@dataclass(frozen=True, slots=True)
class InterruptContext:
    vector:     int
    error_code: int
    rip:        int
    cs:         int
    rflags:     int
    rsp:        int

Handler = Callable[[InterruptContext], None | Awaitable[None]]

# Well-known vector numbers
class Vector:
    DIVIDE_ERROR        = 0x00
    DEBUG               = 0x01
    NMI                 = 0x02
    BREAKPOINT          = 0x03
    OVERFLOW            = 0x04
    BOUND_RANGE         = 0x05
    INVALID_OPCODE      = 0x06
    DEVICE_NOT_AVAIL    = 0x07
    DOUBLE_FAULT        = 0x08
    INVALID_TSS         = 0x0A
    SEG_NOT_PRESENT     = 0x0B
    STACK_SEG_FAULT     = 0x0C
    GENERAL_PROTECTION  = 0x0D
    PAGE_FAULT          = 0x0E
    X87_FPU             = 0x10
    ALIGNMENT_CHECK     = 0x11
    MACHINE_CHECK       = 0x12
    SIMD_FP             = 0x13

class IRQ:
    TIMER       = 0x20  # PIT
    KEYBOARD    = 0x21
    CASCADE     = 0x22
    COM2        = 0x23
    COM1        = 0x24
    LPT2        = 0x25
    FLOPPY      = 0x26
    LPT1        = 0x27
    RTC         = 0x28
    MOUSE       = 0x2C
    FPU         = 0x2D
    ATA0        = 0x2E
    ATA1        = 0x2F


class InterruptRouter:
    def __init__(self) -> None:
        self._table: dict[int, Handler] = {}
        self._loop:  asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        setattr(loop, "_interrupt_dispatch", self._dispatch)

    def register(self, vector: int) -> Callable[[Handler], Handler]:
        def decorator(fn: Handler) -> Handler:
            self._table[vector] = fn
            return fn
        return decorator

    def _dispatch(self, vector: int, error_code: int,
                  rip: int, cs: int, rflags: int, rsp: int) -> None:
        ctx = InterruptContext(vector, error_code, rip, cs, rflags, rsp)
        handler = self._table.get(vector, self._unhandled)
        result = handler(ctx)
        if asyncio.iscoroutine(result):
            if self._loop and self._loop.is_running():
                asyncio.ensure_future(result, loop=self._loop)
            else:
                result.close()   # event loop not yet running; discard tick

    @staticmethod
    def _unhandled(ctx: InterruptContext) -> None:
        if ctx.vector < 0x20:
            # CPU exception with no registered handler — panic
            raise RuntimeError(
                f"Unhandled CPU exception #{ctx.vector:#04x} "
                f"at RIP={ctx.rip:#018x} error={ctx.error_code:#010x}"
            )
        # Spurious IRQ — ignore silently


# Module-level singleton; also exported as `interrupt` decorator
router = InterruptRouter()
interrupt = router.register
