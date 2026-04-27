"""
asyncio — Bare-metal event loop for PythonOS.

Implements a minimal subset of the stdlib asyncio API sufficient to run
the PythonOS kernel:
  - cooperative event loop (no select/socket/selectors)
  - Future / Task / ensure_future
  - sleep() backed by the PIT monotonic clock
  - call_soon_threadsafe() for interrupt-context dispatch
"""

from .events import (
    AbstractEventLoop,
    BareMetalEventLoop,
    get_event_loop,
    set_event_loop,
    new_event_loop,
)
from .futures import Future, InvalidStateError
from .exceptions import CancelledError, TimeoutError
from .tasks import Task, ensure_future, current_task
from .coroutines import iscoroutine
from .queues import Queue, QueueEmpty, QueueFull
from .locks import Event, Lock, Semaphore


async def sleep(delay, result=None):
    """Suspend execution for *delay* seconds, then return *result*."""
    loop = get_event_loop()
    future = loop.create_future()
    loop.call_later(delay, _set_result_unless_cancelled, future, result)
    return await future


def _set_result_unless_cancelled(future, result):
    if not future.cancelled():
        future.set_result(result)


def get_running_loop():
    loop = get_event_loop()
    if loop is None or not loop.is_running():
        raise RuntimeError('no running event loop')
    return loop


async def wait_for(fut, timeout, *, loop=None):
    """Wait for a future/coroutine with an optional timeout (seconds)."""
    _loop = loop or get_event_loop()
    if iscoroutine(fut):
        task = _loop.create_task(fut)
    else:
        task = fut

    if timeout is None:
        return await task

    done = Event()
    result_holder = [None]
    exc_holder    = [None]

    def _on_done(f):
        done.set()

    if hasattr(task, 'add_done_callback'):
        task.add_done_callback(_on_done)

    timeout_expired = [False]
    def _timeout():
        timeout_expired[0] = True
        if hasattr(task, 'cancel') and not task.done():
            task.cancel()
        done.set()

    handle = _loop.call_later(timeout, _timeout)
    await done.wait()

    if hasattr(handle, 'cancel'):
        handle.cancel()

    if timeout_expired[0]:
        raise TimeoutError()

    return task.result()


def gather(*coros_or_futures, return_exceptions=False):
    """Schedule multiple coroutines and return a future for all results."""
    loop = get_event_loop()
    tasks = [loop.create_task(c) if iscoroutine(c) else c
             for c in coros_or_futures]

    outer = loop.create_future()
    results = [None] * len(tasks)
    remaining = [len(tasks)]

    if not tasks:
        outer.set_result([])
        return outer

    def _done(i, t):
        if outer.done():
            return
        if t.cancelled():
            if not return_exceptions:
                outer.cancel()
                return
            results[i] = CancelledError()
        elif t.exception() is not None:
            if not return_exceptions:
                outer.set_exception(t.exception())
                return
            results[i] = t.exception()
        else:
            results[i] = t.result()
        remaining[0] -= 1
        if remaining[0] == 0:
            outer.set_result(results)

    for i, t in enumerate(tasks):
        t.add_done_callback(lambda t, i=i: _done(i, t))

    return outer
