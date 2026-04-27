"""
kernel.scheduler — Kernel process scheduler.

Built on asyncio: every kernel process is an asyncio.Task.
The PIT timer (IRQ 0x20 at 100 Hz) calls scheduler.tick(),
which advances the event loop and tracks wall-clock time.

Preemption is cooperative at await points. True preemption requires
an asyncio event loop that injects cancellation at tick boundaries —
that's a later milestone. For now, tasks must yield at awaitable points.
"""


import asyncio
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Coroutine, Any


class ProcessState(IntEnum):
    RUNNING  = 0
    SLEEPING = 1
    ZOMBIE   = 2


@dataclass
class Process:
    pid:    int
    name:   str
    task:   asyncio.Task
    state:  ProcessState = ProcessState.RUNNING
    ticks:  int = 0           # CPU ticks consumed


class Scheduler:
    TICK_HZ = 100             # must match pit_init() in main.c

    def __init__(self) -> None:
        self._processes: dict[int, Process] = {}
        self._next_pid  = 1
        self._ticks     = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        import _hal
        _hal.set_event_loop(loop)

    # ── Public API ────────────────────────────────────────────────────────────

    def spawn(self, coro: Coroutine, name: str | None = None) -> int:
        pid  = self._next_pid
        self._next_pid += 1
        name = name or f"proc-{pid}"
        task = asyncio.ensure_future(coro, loop=self._loop)
        task.add_done_callback(lambda t: self._reap(pid, t))
        self._processes[pid] = Process(pid=pid, name=name, task=task)
        return pid

    def kill(self, pid: int) -> None:
        proc = self._processes.get(pid)
        if proc and not proc.task.done():
            proc.task.cancel()

    def ps(self) -> list[Process]:
        return list(self._processes.values())

    # ── Timer tick (called by IRQ 0x20 handler) ───────────────────────────────

    def tick(self, ctx) -> None:
        self._ticks += 1
        # Update running process tick count (simplistic: credit the first running task)
        for proc in self._processes.values():
            if proc.state == ProcessState.RUNNING and not proc.task.done():
                proc.ticks += 1
                break

    @property
    def uptime_ms(self) -> int:
        return (self._ticks * 1000) // self.TICK_HZ

    # ── Internals ─────────────────────────────────────────────────────────────

    def _reap(self, pid: int, task: asyncio.Task) -> None:
        proc = self._processes.get(pid)
        if proc:
            proc.state = ProcessState.ZOMBIE
            if task.exception():
                import kernel.log as log
                log.error(f"process {proc.name} (pid={pid}) raised: {task.exception()}")


# Module-level singleton
scheduler = Scheduler()
