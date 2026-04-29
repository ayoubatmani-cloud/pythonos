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
        self._ranges: list[list[int]] = []   # [start, end) physical ranges
        self._free_pages = 0

        for base, length in mmap:
            # Align base up, end down, to page boundaries
            start = (base + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)
            end   = (base + length)        & ~(PAGE_SIZE - 1)

            if start < RESERVED_MB * 1024 * 1024:
                start = RESERVED_MB * 1024 * 1024
            if start < end:
                self._ranges.append([start, end])
                self._free_pages += (end - start) // PAGE_SIZE

    @property
    def free_pages(self) -> int:
        return self._free_pages

    def alloc(self) -> PageFrame:
        while self._ranges:
            region = self._ranges[-1]
            start, end = region
            if start >= end:
                self._ranges.pop()
                continue
            end -= PAGE_SIZE
            region[1] = end
            self._free_pages -= 1
            return PageFrame(phys=end)
        raise MemoryError("Out of physical memory")

    def alloc_n(self, n: int) -> list[PageFrame]:
        if self._free_pages < n:
            raise MemoryError(f"Cannot allocate {n} frames ({self.free_pages} available)")
        return [self.alloc() for _ in range(n)]

    def free(self, frame: PageFrame) -> None:
        self._ranges.append([frame.phys, frame.phys + PAGE_SIZE])
        self._free_pages += 1

    def free_many(self, frames: list[PageFrame]) -> None:
        for frame in frames:
            self.free(frame)
