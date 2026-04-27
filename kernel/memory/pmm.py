"""
kernel.memory.pmm — Physical Memory Manager.

Manages 4 KiB page frames using a free-list backed by a bitmap.
Frames below 1 MiB are reserved (BIOS/legacy regions).
"""


from dataclasses import dataclass

PAGE_SIZE   = 4096
RESERVED_MB = 1   # first 1 MiB is off-limits


@dataclass(slots=True)
class PageFrame:
    phys: int   # physical address of frame


class PhysicalMemoryManager:
    def __init__(self, mmap: list[tuple[int, int]]) -> None:
        self._free: list[int] = []   # physical addresses of free frames

        for base, length in mmap:
            # Align base up, end down, to page boundaries
            start = (base + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)
            end   = (base + length)        & ~(PAGE_SIZE - 1)

            for addr in range(start, end, PAGE_SIZE):
                if addr >= RESERVED_MB * 1024 * 1024:
                    self._free.append(addr)

    @property
    def free_pages(self) -> int:
        return len(self._free)

    def alloc(self) -> PageFrame:
        if not self._free:
            raise MemoryError("Out of physical memory")
        return PageFrame(phys=self._free.pop())

    def alloc_n(self, n: int) -> list[PageFrame]:
        if len(self._free) < n:
            raise MemoryError(f"Cannot allocate {n} frames ({self.free_pages} available)")
        return [PageFrame(phys=self._free.pop()) for _ in range(n)]

    def free(self, frame: PageFrame) -> None:
        self._free.append(frame.phys)

    def free_many(self, frames: list[PageFrame]) -> None:
        self._free.extend(f.phys for f in frames)
