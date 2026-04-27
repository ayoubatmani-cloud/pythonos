"""
kernel — PythonOS kernel package.

Entry point: kernel.boot(mmap, fb_info) is called by the C HAL after
early hardware init. From here, Python owns the machine.
"""


import asyncio

import kernel.log as log
from kernel.hal.io import set_interrupt_router
from kernel.interrupts.router import router
from kernel.interrupts import handlers  # noqa: F401 — registers default handlers
from kernel.memory.pmm import PhysicalMemoryManager
from kernel.memory.vmm import VirtualMemoryManager
from kernel.bus.pci import bus as pci_bus, PCIClass
from kernel.scheduler import scheduler
from kernel.fs.vfs import vfs
from kernel.fs.tmpfs import TmpFS


def boot(mmap: list[tuple[int, int]],
         fb_info: dict | None = None) -> None:
    """
    Called once by the C bootstrap. Never returns.

    mmap:    list of (base_address, length) tuples for usable RAM.
    fb_info: dict with framebuffer parameters, or None.
    """
    log.info("kernel.boot: starting")

    # ── Interrupt routing ──────────────────────────────────────────────────
    set_interrupt_router(router._dispatch)
    log.info("kernel.boot: interrupt router connected")

    # ── Memory ────────────────────────────────────────────────────────────
    pmm = PhysicalMemoryManager(mmap)
    log.info(f"kernel.boot: PMM ready — {pmm.free_pages} pages free "
             f"({pmm.free_pages * 4096 // 1024 // 1024} MiB)")

    vmm = VirtualMemoryManager(pmm)
    # Make vmm accessible to page-fault handler
    import kernel.memory.vmm as _vmm_mod
    _vmm_mod.vmm = vmm
    log.info("kernel.boot: VMM ready")

    # ── PCI enumeration ────────────────────────────────────────────────────
    log.info("kernel.boot: enumerating PCI bus...")
    pci_bus.enumerate()
    log.info(f"kernel.boot: {len(pci_bus)} PCI devices found")
    for dev in pci_bus:
        log.info(f"  {dev}")

    # ── Filesystem ─────────────────────────────────────────────────────────
    root_fs = TmpFS()
    root_fs.seed({
        "dev": {},
        "tmp": {},
        "proc": {},
        "sys": {},
        "bin": {},
    })
    vfs.mount("/", root_fs)
    log.info("kernel.boot: tmpfs mounted at /")

    # ── Event loop ─────────────────────────────────────────────────────────
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    router.set_event_loop(loop)
    scheduler.attach_loop(loop)   # also registers loop with _hal for threadsafe dispatch
    log.info("kernel.boot: event loop ready")

    log.info("kernel.boot: entering main loop")
    loop.run_until_complete(_kernel_main(pmm, vmm, fb_info))


async def _kernel_main(
    pmm: PhysicalMemoryManager,
    vmm: VirtualMemoryManager,
    fb_info: dict | None,
) -> None:
    log.info("kernel: async main started")

    # ── Framebuffer + console ──────────────────────────────────────────────
    import sys as _sys
    import kernel.display as display
    import kernel.display.framebuffer
    import kernel.display.console
    _fb_mod      = _sys.modules['kernel.display.framebuffer']
    _console_mod = _sys.modules['kernel.display.console']

    if fb_info:
        fb = display.Framebuffer(fb_info)
        _fb_mod.fb = fb
        console = display.Console(fb)
        _console_mod.console = console
        console.writeln("PythonOS")
        console.writeln(f"RAM: {pmm.free_pages * 4096 // 1024 // 1024} MiB free")
        log.info("kernel: framebuffer console ready")
    else:
        console = None
        log.info("kernel: no framebuffer — serial only")

    # ── Keyboard ───────────────────────────────────────────────────────────
    from kernel.drivers.keyboard import keyboard
    keyboard.init()
    log.info("kernel: keyboard driver ready")

    # ── Register PCI drivers before binding ───────────────────────────────
    from kernel.drivers.net.virtio_net import VirtIONetDriver, VIRTIO_VENDOR, VIRTIO_NET_DEV
    from kernel.sound.hda import HDADriver, HDA_VENDOR_INTEL, HDA_DEVICE_ICH6
    pci_bus.register_driver(VirtIONetDriver, vendor=VIRTIO_VENDOR, device=VIRTIO_NET_DEV)
    pci_bus.register_driver(HDADriver, vendor=HDA_VENDOR_INTEL, device=HDA_DEVICE_ICH6)

    # ── PCI driver binding ─────────────────────────────────────────────────
    pci_bus.bind_drivers()

    # ── Network ────────────────────────────────────────────────────────────
    nic = next((dev.driver for dev in pci_bus
                if isinstance(dev.driver, VirtIONetDriver)), None)
    if nic:
        from kernel.net.stack import net_init
        scheduler.spawn(net_init(nic, "10.0.2.15", "10.0.2.2"), name="net-init")
        log.info("kernel: network stack starting")

    # ── Sound ──────────────────────────────────────────────────────────────
    import kernel.sound.hda
    _hda_mod = _sys.modules['kernel.sound.hda']
    hda_dev = next((dev.driver for dev in pci_bus
                    if isinstance(getattr(dev, 'driver', None), _hda_mod.HDADriver)), None)
    if hda_dev:
        _hda_mod.hda = hda_dev
        log.info("kernel: HDA sound ready")

    # ── Shell ──────────────────────────────────────────────────────────────
    from kernel.shell import Shell

    def _write(text: str) -> None:
        if console:
            console.write(text)
        else:
            log._serial(text)

    shell = Shell(read_char=keyboard.read_char, write=_write)

    # Spawn shell as a kernel process
    scheduler.spawn(shell.run(), name="kshell")

    log.info("kernel: shell spawned — system ready")

    # Main loop: keep the event loop alive; subsystems run as tasks
    while True:
        await asyncio.sleep(0.1)
