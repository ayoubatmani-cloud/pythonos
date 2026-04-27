"""asyncio.queues — bare-metal Queue implementation."""

from .exceptions import CancelledError
from .events import get_event_loop


class QueueEmpty(Exception):
    pass


class QueueFull(Exception):
    pass


class Queue:
    def __init__(self, maxsize=0):
        self._maxsize = maxsize
        self._items   = []
        self._getters = []   # Futures waiting for an item
        self._putters = []   # Futures waiting for space

    def qsize(self):
        return len(self._items)

    def empty(self):
        return not self._items

    def full(self):
        return 0 < self._maxsize <= len(self._items)

    def put_nowait(self, item):
        if self.full():
            raise QueueFull()
        self._items.append(item)
        self._wakeup_getter()

    def get_nowait(self):
        if not self._items:
            raise QueueEmpty()
        item = self._items.pop(0)
        self._wakeup_putter()
        return item

    async def put(self, item):
        while self.full():
            loop = get_event_loop()
            fut = loop.create_future()
            self._putters.append(fut)
            try:
                await fut
            except CancelledError:
                try:
                    self._putters.remove(fut)
                except ValueError:
                    pass
                raise
        self.put_nowait(item)

    async def get(self):
        while not self._items:
            loop = get_event_loop()
            fut = loop.create_future()
            self._getters.append(fut)
            try:
                await fut
            except CancelledError:
                try:
                    self._getters.remove(fut)
                except ValueError:
                    pass
                raise
        return self.get_nowait()

    def _wakeup_getter(self):
        while self._getters:
            fut = self._getters.pop(0)
            if not fut.done():
                fut.set_result(None)
                break

    def _wakeup_putter(self):
        while self._putters:
            fut = self._putters.pop(0)
            if not fut.done():
                fut.set_result(None)
                break

    def __repr__(self):
        return (f'<Queue maxsize={self._maxsize!r} qsize={self.qsize()}>')
