# PythonOS

A bare-metal operating system where CPython 3.14 **is** the kernel — not a program running on an OS, but the OS itself. Python owns the machine from interrupt handlers to the interactive shell.

## Quick Start

### Prerequisites

- Docker (for cross-compilation toolchain)
- QEMU (`brew install qemu` on macOS)
- CPython 3.14 source tree (fetched by the build)

### Build

```bash
# First time: fetch and cross-compile CPython for bare metal (~10 min)
make docker-build       # build the Docker cross-compilation image
make cpython-build      # build libpython3.14.a inside Docker

# Every subsequent build
make docker-iso         # freeze kernel, compile, link, create pythonos.iso
```

### Run

```bash
# Boot in QEMU, serial output to terminal
make qemu-iso

# Capture serial output to file (useful for debugging)
timeout 30 qemu-system-x86_64 \
  -machine q35 -cpu qemu64 -m 512M \
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
  -device intel-hda -device hda-duplex \
  -no-reboot -no-shutdown \
  -cdrom pythonos.iso -boot d \
  -display none -serial file:/tmp/serial.log
cat /tmp/serial.log
```

Expected boot output:
```
[PythonOS] INFO  kernel.boot: PMM ready — 510 MiB free
[PythonOS] INFO  kernel.boot: 7 PCI devices found
[PythonOS] INFO  kernel.boot: tmpfs mounted at /
[PythonOS] INFO  kernel: framebuffer console ready
[PythonOS] INFO  virtio-net: MAC 52:54:00:12:34:56
[PythonOS] INFO  hda: driver ready
[PythonOS] INFO  kernel: shell spawned — system ready
[PythonOS] INFO  net: configured 10.0.2.15 gw=10.0.2.2

PythonOS kernel shell
Python 3.14.0
Type 'help' for kernel commands.

>>>
```

### Use the Shell

The `>>>` prompt is a live Python REPL with full kernel access:

```python
>>> pci                         # inspect the PCI bus
>>> scheduler.tasks()           # list running kernel tasks
>>> vfs.ls("/")                 # browse the filesystem
>>> import kernel.log as log; log.info("hello")
>>> kernel.memory.pmm.free_pages
```

---

## What Is This?

Most operating systems are written in C, with scripting languages bolted on top as userspace programs. PythonOS inverts that: the Python interpreter **is** the kernel primitive. There is no C runtime managing Python — Python manages the machine.

The philosophical bet: "everything is an object" is a better organizing principle for a kernel than "everything is a file." `importlib`, `exec`, and `inspect` become the OS hot-reload and introspection syscalls. The system can extend itself at runtime without rebooting.

### Boot Sequence

```
GRUB2 (multiboot2)
  └─▶ boot.asm — long mode, 4 GiB identity map, 4 MiB stack
        └─▶ main.c — GDT, IDT, PIC, PIT, serial
              └─▶ hal.c — CPython init, freeze frozen modules
                    └─▶ kernel.boot() — Python owns the machine
                          ├─▶ PMM + VMM
                          ├─▶ PCI enumeration + driver binding
                          ├─▶ asyncio event loop
                          ├─▶ Framebuffer console
                          ├─▶ VirtIO-net, Intel HDA
                          ├─▶ Network stack (ARP/IP/TCP)
                          └─▶ Interactive kernel shell
```

### Source Layout

```
src/
  boot/       asm + C bootstrap: GDT, IDT, PIC, PIT, serial, framebuffer
  hal/        hal.c — _hal Python C extension (port I/O, MMIO, interrupts, DMA)
  libc/       freestanding libc: buddy allocator, string, stdio, POSIX stubs

kernel/
  __init__.py        boot() entry point — wires all subsystems
  hal/               thin Python wrapper over _hal
  interrupts/        interrupt router, @interrupt decorator, default handlers
  bus/pci.py         PCI enumeration (CF8/CFC), driver Protocol, PCIBus
  memory/            PMM (page frame allocator), VMM (virtual address spaces)
  drivers/
    keyboard.py      PS/2 keyboard driver (async character queue)
    net/virtio_net.py  VirtIO-net driver (DMA descriptor rings)
  sound/hda.py       Intel HDA driver (BDL DMA, codec configuration)
  net/               ARP, IP, TCP, network stack initialization
  fs/                VFS + tmpfs
  scheduler.py       asyncio task scheduler
  shell.py           interactive Python kernel shell
  display/           framebuffer + bitmap font console
  log.py             early serial logging via _hal

asyncio/             bare-metal asyncio (no socket/selectors): Future, Task,
                     Queue, Event, Lock, Semaphore, sleep, wait_for, gather

tools/
  freeze_kernel.py   compiles kernel/*.py → frozen C bytecode in the ELF
  stdlib_stubs/      bare-metal replacements for stdlib modules that assume
                     a POSIX host (dataclasses, functools, os, ctypes, …)
  Dockerfile         Ubuntu 24.04 cross-compilation environment
  setup_cpython.sh   fetch, patch, and configure CPython 3.14 for bare metal

deps/
  Modules.Setup.local  CPython built-in module list (excludes socket/select/…)
  cpython/           built libpython3.14.a + headers (generated; not in git)
  cpython-src/       CPython 3.14.0 source (generated; not in git)
```

---

## Architecture Notes

### CPython on Bare Metal

CPython 3.14.0 is compiled as a static library (`libpython3.14.a`) linked directly into the kernel ELF. `Py_Initialize()` runs before any Python code; from that point forward, the Python interpreter is the kernel runtime.

All kernel Python modules are **frozen** — compiled to bytecode and embedded in the ELF as C arrays. There is no filesystem required for `import`. The freeze tool (`tools/freeze_kernel.py`) runs at build time and produces `build/frozen_kernel.c`.

### `_hal` C Extension

`src/hal/hal.c` implements the `_hal` built-in Python module, compiled into the kernel. It exposes:

| Function | Description |
|---|---|
| `inb/inw/inl(port)` | Port I/O reads |
| `outb/outw/outl(port, val)` | Port I/O writes |
| `mmio_read8/32(addr)` | Memory-mapped I/O reads |
| `mmio_write32(addr, val)` | Memory-mapped I/O write |
| `dma_alloc(size)` | Allocate zeroed C-heap DMA buffer, return physical address |
| `buf_addr(bytearray)` | Return physical address of bytearray's internal buffer |
| `read_cr2/cr3()` | Control register reads |
| `set_interrupt_router(fn)` | Register Python interrupt dispatcher |
| `set_event_loop(loop)` | Register asyncio loop for interrupt-safe dispatch |

### DMA Memory

Python's garbage collector must never touch DMA buffers (device-visible memory). `_hal.dma_alloc(n)` allocates from the C buddy allocator (`calloc`) and returns an integer physical address. The GC cannot see this allocation. This is used by VirtIO-net descriptor rings, HDA BDLs, and RX packet buffers.

### Bare-Metal asyncio

The `asyncio/` package is a from-scratch implementation of the asyncio API — no `select`, no sockets, no `selectors`. The event loop is driven by the PIT timer (100 Hz) and hardware interrupt callbacks routed through `call_soon_threadsafe`. Full API: `Future`, `Task`, `Queue`, `Event`, `Lock`, `Semaphore`, `sleep`, `wait_for`, `gather`, `ensure_future`.

### Stdlib Stubs

Several stdlib modules assume a POSIX host and break on bare metal. `tools/stdlib_stubs/` contains replacements:

| Stub | Why it exists |
|---|---|
| `dataclasses.py` | CPython's version uses `exec()` to generate `__init__` etc., which fails on bare metal with a spurious `SyntaxError`. Rewritten using closures. |
| `functools.py` | `_CacheInfo = namedtuple(...)` uses `eval()`. Replaced with a plain class. |
| `os.py` | The real `os.py` imports `posix` which expects `_have_functions`. Minimal stub. |
| `ctypes/__init__.py` | `_ctypes` is not compiled in (requires libffi). Minimal stub for `addressof`; prefer `_hal.dma_alloc` for DMA. |
| `random.py` | Minimal LCG PRNG seeded from PIT port reads. |
| `traceback.py` | CPython 3.14's version imports `_colorize` (not compiled in). Minimal format_exc. |
| `linecache.py` | No source files on bare metal; no-op cache. |
| `inspect.py`, `pathlib.py` | Minimal stubs used during module discovery. |

---

## Building CPython for Bare Metal

The CPython configuration disables everything that requires a host OS:

- No `socket`, `select`, `selectors`, `ssl`, `readline`, `termios`
- No `fork`, `exec`, `subprocess`
- No dynamic loading (`dlopen`)
- Built-in modules only: `_struct`, `_collections`, `_functools`, `_io`, `_signal`, `math`, `_warnings`, `_weakref`, `_abc`, `_json`, `_csv`, `_datetime`, `_pickle`, `_random`, `_bisect`, `_heapq`, `_operator`, `_stat`, `array`, `binascii`, `zlib`, `_hashlib`, `_sha256`, `_sha512`, `_blake2`, `_md5`, and `_hal`

See `deps/Modules.Setup.local` for the complete list and `tools/setup_cpython.sh` for the configure flags.

---

## License

BSD 2-Clause. See [LICENSE](LICENSE).
