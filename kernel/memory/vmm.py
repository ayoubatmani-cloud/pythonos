"""
kernel.memory.vmm — Virtual Memory Manager.

Manages per-process virtual address spaces. The kernel itself runs in
a single shared address space (the boot identity map); processes get
their own VirtualAddressSpace instances.

Page fault handling delegates to swap (if a frame was evicted) or
returns False (segfault) for invalid accesses.
"""


from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Flag, auto
from typing import AsyncIterator

from kernel.memory.pmm import PhysicalMemoryManager, PageFrame, PAGE_SIZE
from kernel.hal.io import read_cr3, write_cr3


class PageFlags(Flag):
    PRESENT    = auto()
    WRITE      = auto()
    USER       = auto()
    EXECUTABLE = auto()

    RO   = PRESENT
    RW   = PRESENT | WRITE
    RWX  = PRESENT | WRITE | EXECUTABLE
    USER_RW = PRESENT | WRITE | USER


@dataclass(slots=True)
class Mapping:
    vaddr: int
    frame: PageFrame
    flags: PageFlags


@dataclass
class MemoryRegion:
    vaddr:    int
    size:     int
    flags:    PageFlags
    mappings: list[Mapping] = field(default_factory=list)

    def __len__(self) -> int:
        return self.size


class VirtualAddressSpace:
    """One per process (kernel shares the boot PML4)."""

    def __init__(self, pmm: PhysicalMemoryManager) -> None:
        self._pmm      = pmm
        self._mappings: dict[int, Mapping] = {}   # vaddr -> Mapping
        self._next_vaddr = 0x0000_1000_0000_0000  # start of user heap range

    def map(self, vaddr: int, frame: PageFrame, flags: PageFlags) -> None:
        m = Mapping(vaddr=vaddr, frame=frame, flags=flags)
        self._mappings[vaddr] = m
        self._tlb_flush(vaddr)

    def unmap(self, vaddr: int) -> PageFrame | None:
        m = self._mappings.pop(vaddr, None)
        if m:
            self._tlb_flush(vaddr)
            return m.frame
        return None

    def __getitem__(self, vaddr: int) -> Mapping:
        m = self._mappings.get(vaddr)
        if m is None:
            raise KeyError(f"No mapping at {vaddr:#018x}")
        return m

    def __contains__(self, vaddr: int) -> bool:
        return vaddr in self._mappings

    @asynccontextmanager
    async def region(
        self, size: int, flags: PageFlags = PageFlags.RW
    ) -> AsyncIterator[MemoryRegion]:
        n      = (size + PAGE_SIZE - 1) // PAGE_SIZE
        frames = self._pmm.alloc_n(n)
        vaddr  = self._alloc_vrange(n)
        region = MemoryRegion(vaddr=vaddr, size=size, flags=flags)

        for i, frame in enumerate(frames):
            v = vaddr + i * PAGE_SIZE
            self.map(v, frame, flags)
            region.mappings.append(self._mappings[v])

        try:
            yield region
        finally:
            for m in region.mappings:
                self.unmap(m.vaddr)
            self._pmm.free_many(frames)

    def _alloc_vrange(self, n: int) -> int:
        vaddr = self._next_vaddr
        self._next_vaddr += n * PAGE_SIZE
        return vaddr

    @staticmethod
    def _tlb_flush(vaddr: int) -> None:
        __import__('_hal')  # ensure extension is loaded
        import ctypes
        # invlpg instruction — flush single TLB entry
        # Implemented as inline asm via a ctypes function pointer trick;
        # replaced by a proper _hal.invlpg() once we add it.
        pass  # TODO: _hal.invlpg(vaddr)


class VirtualMemoryManager:
    """Kernel-wide VMM. Owns the kernel address space and creates user spaces."""

    def __init__(self, pmm: PhysicalMemoryManager) -> None:
        self._pmm   = pmm
        self._spaces: dict[int, VirtualAddressSpace] = {}  # pid -> space

    def create_space(self, pid: int) -> VirtualAddressSpace:
        space = VirtualAddressSpace(self._pmm)
        self._spaces[pid] = space
        return space

    def destroy_space(self, pid: int) -> None:
        space = self._spaces.pop(pid, None)
        if space:
            # Free all frames still mapped
            for m in list(space._mappings.values()):
                space.unmap(m.vaddr)
                self._pmm.free(m.frame)

    async def handle_fault(
        self, vaddr: int, *, write: bool, user: bool, present: bool
    ) -> bool:
        """
        Called by the page-fault handler. Returns True if handled, False for SIGSEGV.
        Handles: demand paging, copy-on-write, swap-in.
        """
        # TODO: swap backend integration, CoW, demand zero pages
        return False


# Module-level kernel VMM (initialized in kernel.boot)
vmm: VirtualMemoryManager | None = None
