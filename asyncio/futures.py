from .exceptions import CancelledError, InvalidStateError

_PENDING   = 'PENDING'
_CANCELLED = 'CANCELLED'
_FINISHED  = 'FINISHED'


class Future:
    _asyncio_future_blocking = False

    def __init__(self, loop=None):
        self._loop      = loop
        self._state     = _PENDING
        self._result    = None
        self._exception = None
        self._callbacks = []

    def cancelled(self):
        return self._state == _CANCELLED

    def done(self):
        return self._state != _PENDING

    def result(self):
        if self._state == _CANCELLED:
            raise CancelledError()
        if self._state != _FINISHED:
            raise InvalidStateError('Future is not done')
        if self._exception is not None:
            raise self._exception
        return self._result

    def exception(self):
        if self._state == _CANCELLED:
            raise CancelledError()
        if self._state != _FINISHED:
            raise InvalidStateError('Future is not done')
        return self._exception

    def set_result(self, result):
        if self._state != _PENDING:
            raise InvalidStateError(f'Future state is already {self._state}')
        self._result = result
        self._state  = _FINISHED
        self._schedule_callbacks()

    def set_exception(self, exception):
        if self._state != _PENDING:
            raise InvalidStateError(f'Future state is already {self._state}')
        if isinstance(exception, type):
            exception = exception()
        self._exception = exception
        self._state     = _FINISHED
        self._schedule_callbacks()

    def cancel(self, msg=None):
        if self._state != _PENDING:
            return False
        self._state = _CANCELLED
        self._schedule_callbacks()
        return True

    def add_done_callback(self, fn, context=None):
        if self._state != _PENDING:
            if self._loop:
                self._loop.call_soon(fn, self)
            else:
                fn(self)
        else:
            self._callbacks.append(fn)

    def remove_done_callback(self, fn):
        before = len(self._callbacks)
        self._callbacks = [f for f in self._callbacks if f != fn]
        return before - len(self._callbacks)

    def _schedule_callbacks(self):
        callbacks = self._callbacks[:]
        self._callbacks = []
        for fn in callbacks:
            if self._loop:
                self._loop.call_soon(fn, self)
            else:
                try:
                    fn(self)
                except Exception:
                    pass

    def __await__(self):
        if not self.done():
            self._asyncio_future_blocking = True
            yield self
        if not self.done():
            raise RuntimeError('await was not used with a Future')
        return self.result()

    __iter__ = __await__
