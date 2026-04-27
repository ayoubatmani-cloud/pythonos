from .futures import Future
from .exceptions import CancelledError


class Task(Future):
    def __init__(self, coro, loop=None, name=None):
        super().__init__(loop=loop)
        self._coro         = coro
        self._fut_waiter   = None
        self._must_cancel  = False
        self._name         = name or getattr(coro, '__qualname__', repr(coro))

    def get_name(self):
        return self._name

    def cancel(self, msg=None):
        self._must_cancel = True
        if self._fut_waiter is not None:
            return self._fut_waiter.cancel(msg=msg)
        return True

    def _step(self, exc=None):
        coro = self._coro
        self._fut_waiter = None

        if self._must_cancel:
            if not isinstance(exc, CancelledError):
                exc = CancelledError()
            self._must_cancel = False

        try:
            if exc is None:
                result = coro.send(None)
            else:
                result = coro.throw(type(exc), exc, exc.__traceback__)
        except StopIteration as stop:
            super().set_result(stop.value)
            return
        except CancelledError:
            super().cancel()
            return
        except BaseException as exc:
            super().set_exception(exc)
            return

        # Coroutine yielded — check what it is
        blocking = getattr(result, '_asyncio_future_blocking', None)
        if blocking is not None:
            # It yielded a Future; wait for it
            result._asyncio_future_blocking = False
            self._fut_waiter = result
            result.add_done_callback(self._wakeup)
        else:
            # Yielded None or something else; re-schedule next iteration
            if self._loop:
                self._loop.call_soon(self._step)

    def _wakeup(self, future):
        try:
            future.result()
        except BaseException as exc:
            self._step(exc)
        else:
            self._step()


def ensure_future(coro_or_future, loop=None):
    from .events import get_event_loop
    from .coroutines import iscoroutine
    if loop is None:
        loop = get_event_loop()
    if iscoroutine(coro_or_future):
        task = Task(coro_or_future, loop=loop)
        loop.call_soon(task._step)
        return task
    if isinstance(coro_or_future, Future):
        return coro_or_future
    raise TypeError(f'Expected coroutine or Future, got {type(coro_or_future)!r}')


def current_task(loop=None):
    return None
