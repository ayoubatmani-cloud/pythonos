"""
kernel.interrupts.handlers — Default kernel interrupt handlers.

Import this module to wire up the standard handler set.
Drivers register their own handlers on top of these.
"""

from kernel.interrupts.router import router, interrupt, InterruptContext, Vector, IRQ
from kernel.hal.io import read_cr2
import kernel.log as log


@interrupt(Vector.PAGE_FAULT)
async def _page_fault(ctx: InterruptContext) -> None:
    cr2 = read_cr2()
    present     = bool(ctx.error_code & 0x01)
    write       = bool(ctx.error_code & 0x02)
    user_mode   = bool(ctx.error_code & 0x04)

    from kernel.memory.vmm import vmm
    handled = await vmm.handle_fault(
        vaddr=cr2,
        write=write,
        user=user_mode,
        present=present,
    )
    if not handled:
        raise RuntimeError(
            f"Page fault: {'present' if present else 'not-present'} "
            f"{'write' if write else 'read'} at {cr2:#018x} "
            f"(RIP={ctx.rip:#018x})"
        )


@interrupt(Vector.GENERAL_PROTECTION)
def _gpf(ctx: InterruptContext) -> None:
    raise RuntimeError(
        f"General protection fault: error={ctx.error_code:#010x} "
        f"RIP={ctx.rip:#018x}"
    )


@interrupt(Vector.DOUBLE_FAULT)
def _double_fault(ctx: InterruptContext) -> None:
    # Double fault is unrecoverable — halt immediately
    import _hal  # avoid circular imports
    log.panic(f"Double fault at RIP={ctx.rip:#018x}")


@interrupt(Vector.INVALID_OPCODE)
def _invalid_opcode(ctx: InterruptContext) -> None:
    raise RuntimeError(f"Invalid opcode at RIP={ctx.rip:#018x}")


@interrupt(Vector.DIVIDE_ERROR)
def _divide_error(ctx: InterruptContext) -> None:
    raise ZeroDivisionError(f"Divide-by-zero at RIP={ctx.rip:#018x}")


@interrupt(IRQ.TIMER)
def _timer(ctx: InterruptContext) -> None:
    from kernel.scheduler import scheduler
    scheduler.tick(ctx)


# IRQ.KEYBOARD is registered by the PS/2 driver itself in
# kernel.drivers.keyboard — don't shadow it from here.
