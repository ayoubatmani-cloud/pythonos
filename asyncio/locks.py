"""asyncio.locks — bare-metal Event, Lock, and Semaphore."""

from .exceptions import CancelledError
from .events import get_event_loop


class Event:
    """A synchronization primitive that can be awaited."""

    def __init__(self):
        self._flag    = False
        self._waiters = []

    def is_set(self):
        return self._flag

    def set(self):
        if not self._flag:
            self._flag = True
            for fut in self._waiters:
                if not fut.done():
                    fut.set_result(None)
            self._waiters.clear()

    def clear(self):
        self._flag = False

    async def wait(self):
        if self._flag:
            return True
        loop = get_event_loop()
        fut  = loop.create_future()
        self._waiters.append(fut)
        try:
            await fut
        except CancelledError:
            try:
                self._waiters.remove(fut)
            except ValueError:
                pass
            raise
        return True

    def __repr__(self):
        return f'<Event set={self._flag!r}>'


class Lock:
    def __init__(self):
        self._locked  = False
        self._waiters = []

    def locked(self):
        return self._locked

    async def acquire(self):
        if not self._locked:
            self._locked = True
            return True
        loop = get_event_loop()
        fut  = loop.create_future()
        self._waiters.append(fut)
        try:
            await fut
        except CancelledError:
            try:
                self._waiters.remove(fut)
            except ValueError:
                pass
            raise
        self._locked = True
        return True

    def release(self):
        if not self._locked:
            raise RuntimeError('Lock is not acquired')
        self._locked = False
        for fut in self._waiters:
            if not fut.done():
                fut.set_result(None)
                self._waiters.remove(fut)
                break

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()


class Semaphore:
    def __init__(self, value=1):
        if value < 0:
            raise ValueError('Semaphore value must be >= 0')
        self._value   = value
        self._waiters = []

    def locked(self):
        return self._value == 0

    async def acquire(self):
        while self._value <= 0:
            loop = get_event_loop()
            fut  = loop.create_future()
            self._waiters.append(fut)
            try:
                await fut
            except CancelledError:
                try:
                    self._waiters.remove(fut)
                except ValueError:
                    pass
                raise
        self._value -= 1
        return True

    def release(self):
        self._value += 1
        for fut in self._waiters:
            if not fut.done():
                fut.set_result(None)
                break

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()
