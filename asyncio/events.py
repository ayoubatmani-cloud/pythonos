_current_loop = None


def get_event_loop():
    global _current_loop
    if _current_loop is None:
        _current_loop = new_event_loop()
    return _current_loop


def set_event_loop(loop):
    global _current_loop
    _current_loop = loop


def new_event_loop():
    return BareMetalEventLoop()


class AbstractEventLoop:
    def run_until_complete(self, coro):
        raise NotImplementedError

    def call_soon(self, fn, *args, context=None):
        raise NotImplementedError

    def call_soon_threadsafe(self, fn, *args, context=None):
        raise NotImplementedError

    def call_later(self, delay, fn, *args, context=None):
        raise NotImplementedError

    def call_at(self, when, fn, *args, context=None):
        raise NotImplementedError

    def create_future(self):
        raise NotImplementedError

    def create_task(self, coro, name=None):
        raise NotImplementedError

    def is_running(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class _Handle:
    __slots__ = ('_fn', '_args', '_cancelled')

    def __init__(self, fn, args):
        self._fn        = fn
        self._args      = args
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _run(self):
        if not self._cancelled:
            try:
                self._fn(*self._args)
            except Exception as exc:
                import sys
                sys.stderr.write(f'asyncio: exception in callback {self._fn!r}: {exc}\n')


def _monotonic():
    try:
        import time as _t
        return _t.monotonic()
    except Exception:
        return 0.0


class BareMetalEventLoop(AbstractEventLoop):
    def __init__(self):
        self._ready     = []   # list of _Handle
        self._scheduled = []   # sorted list of (when, _Handle)
        self._running   = False
        self._stopping  = False

    def is_running(self):
        return self._running

    def stop(self):
        self._stopping = True

    def close(self):
        self._ready     = []
        self._scheduled = []

    def call_soon(self, fn, *args, context=None):
        handle = _Handle(fn, args)
        self._ready.append(handle)
        return handle

    def call_soon_threadsafe(self, fn, *args, context=None):
        handle = _Handle(fn, args)
        self._ready.append(handle)
        return handle

    def call_later(self, delay, fn, *args, context=None):
        when = _monotonic() + delay
        return self.call_at(when, fn, *args, context=context)

    def call_at(self, when, fn, *args, context=None):
        handle = _Handle(fn, args)
        # Insert into the sorted list
        i = 0
        while i < len(self._scheduled) and self._scheduled[i][0] <= when:
            i += 1
        self._scheduled.insert(i, (when, handle))
        return handle

    def create_future(self):
        from .futures import Future
        return Future(loop=self)

    def create_task(self, coro, name=None):
        from .tasks import Task
        task = Task(coro, loop=self, name=name)
        self.call_soon(task._step)
        return task

    def run_until_complete(self, coro_or_future):
        from .coroutines import iscoroutine
        from .exceptions import CancelledError

        if iscoroutine(coro_or_future):
            future = self.create_task(coro_or_future)
        else:
            future = coro_or_future

        self._running  = True
        self._stopping = False
        try:
            while not future.done() and not self._stopping:
                self._run_once()
        finally:
            self._running = False

        if future.cancelled():
            raise CancelledError()
        return future.result()

    def _run_once(self):
        now = _monotonic()

        dispatch = getattr(self, "_interrupt_dispatch", None)
        if dispatch is not None:
            try:
                import _hal
                for irq in _hal.drain_interrupts():
                    dispatch(*irq)
            except Exception as exc:
                import sys
                sys.stderr.write(f'asyncio: exception draining interrupts: {exc}\n')

        # Promote scheduled callbacks that are past due
        while self._scheduled and self._scheduled[0][0] <= now:
            _, handle = self._scheduled.pop(0)
            self._ready.append(handle)

        # Run all currently ready callbacks.
        ntodo = len(self._ready)
        for _ in range(ntodo):
            if not self._ready:
                break
            handle = self._ready.pop(0)
            handle._run()
