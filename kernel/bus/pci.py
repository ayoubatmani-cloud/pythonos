"""
kernel.bus.pci — PCI/PCIe configuration space enumeration and driver binding.

PCI config space is accessed via the legacy port I/O mechanism (CF8/CFC).
PCIe ECAM (MMIO-based) access is a later extension layered on top.

Usage:
    bus = PCIBus()
    bus.enumerate()
    for dev in bus:
        print(dev)
    bus.bind_drivers()
"""


from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterator, Protocol, runtime_checkable

import _hal as _hal_mod
from kernel.hal.io import inl, outl

# ── PCI config space I/O ──────────────────────────────────────────────────────

_ARCH = getattr(_hal_mod, 'ARCH', 'x86_64')

CONFIG_ADDRESS = 0xCF8
CONFIG_DATA    = 0xCFC

def _addr(bus: int, dev: int, func: int, offset: int) -> int:
    return (1 << 31) | (bus << 16) | (dev << 11) | (func << 8) | (offset & 0xFC)


if _ARCH == 'arm64':
    # PCIe ECAM (Enhanced Configuration Access Mechanism) on QEMU virt arm64.
    # Config space at 0x4010000000; each function occupies 4KB.
    _ECAM_BASE = 0x4010000000

    def config_read32(bus: int, dev: int, func: int, offset: int) -> int:
        addr = _ECAM_BASE | (bus << 20) | (dev << 15) | (func << 12) | (offset & 0xFFC)
        return _hal_mod.mmio_read32(addr)
else:
    def config_read32(bus: int, dev: int, func: int, offset: int) -> int:
        outl(CONFIG_ADDRESS, _addr(bus, dev, func, offset))
        return inl(CONFIG_DATA)


def config_read16(bus: int, dev: int, func: int, offset: int) -> int:
    raw = config_read32(bus, dev, func, offset)
    return (raw >> ((offset & 2) * 8)) & 0xFFFF

def config_read8(bus: int, dev: int, func: int, offset: int) -> int:
    raw = config_read32(bus, dev, func, offset)
    return (raw >> ((offset & 3) * 8)) & 0xFF


# ── PCI class codes ───────────────────────────────────────────────────────────

class PCIClass(IntEnum):
    UNCLASSIFIED    = 0x00
    STORAGE         = 0x01
    NETWORK         = 0x02
    DISPLAY         = 0x03
    MULTIMEDIA      = 0x04
    MEMORY_CTL      = 0x05
    BRIDGE          = 0x06
    SIMPLE_COMM     = 0x07
    BASE_PERIPH     = 0x08
    INPUT           = 0x09
    DOCKING         = 0x0A
    PROCESSOR       = 0x0B
    SERIAL_BUS      = 0x0C
    WIRELESS        = 0x0D
    INTELLIGENT_IO  = 0x0E
    SATELLITE       = 0x0F
    ENCRYPTION      = 0x10
    SIGNAL_PROC     = 0x11
    UNKNOWN         = 0xFF

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PCIAddress:
    bus:      int
    device:   int
    function: int

    def __str__(self) -> str:
        return f"{self.bus:04x}:{self.device:02x}.{self.function}"


@dataclass(slots=True)
class PCIDevice:
    addr:       PCIAddress
    vendor_id:  int
    device_id:  int
    class_code: PCIClass
    subclass:   int
    prog_if:    int
    revision:   int
    bars:       list[int] = field(default_factory=list)
    # Set by bind_drivers()
    driver:     object | None = field(default=None, compare=False)

    @property
    def id_str(self) -> str:
        return f"{self.vendor_id:04x}:{self.device_id:04x}"

    def __str__(self) -> str:
        return (f"[{self.addr}] {self.class_code.name} "
                f"vendor={self.vendor_id:04x} device={self.device_id:04x}")


# ── Driver Protocol ───────────────────────────────────────────────────────────

@runtime_checkable
class PCIDriver(Protocol):
    def probe(self, device: PCIDevice) -> bool: ...
    def remove(self, device: PCIDevice) -> None: ...


# ── PCI Bus ───────────────────────────────────────────────────────────────────

class PCIBus:
    def __init__(self) -> None:
        self._devices: dict[PCIAddress, PCIDevice] = {}
        # Match order: (vendor, device) > (vendor, None) > (None, class_code)
        self._by_id:    dict[tuple[int, int], type[PCIDriver]] = {}
        self._by_vendor:dict[int, type[PCIDriver]]             = {}
        self._by_class: dict[PCIClass, type[PCIDriver]]        = {}

    def enumerate(self) -> None:
        """Scan all 256 buses. In practice most systems have 1-4."""
        for bus in range(256):
            for dev in range(32):
                self._probe(bus, dev, 0)

    def _read_bars(self, bus: int, dev: int, func: int) -> list[int]:
        bars = []
        for i in range(6):
            raw = config_read32(bus, dev, func, 0x10 + i * 4)
            if raw == 0:
                continue
            # Determine BAR size: write all-1s, read back
            from kernel.hal.io import outl as _outl
            # (BAR sizing omitted for initial enumeration — store raw address)
            bars.append(raw)
        return bars

    def _probe(self, bus: int, dev: int, func: int) -> PCIDevice | None:
        vid_did = config_read32(bus, dev, func, 0x00)
        if (vid_did & 0xFFFF) == 0xFFFF:
            return None   # no device

        vendor_id = vid_did & 0xFFFF
        device_id = (vid_did >> 16) & 0xFFFF

        class_rev  = config_read32(bus, dev, func, 0x08)
        revision   = class_rev & 0xFF
        prog_if    = (class_rev >> 8) & 0xFF
        subclass   = (class_rev >> 16) & 0xFF
        class_code = PCIClass((class_rev >> 24) & 0xFF)

        addr   = PCIAddress(bus, dev, func)
        device = PCIDevice(
            addr=addr,
            vendor_id=vendor_id,
            device_id=device_id,
            class_code=class_code,
            subclass=subclass,
            prog_if=prog_if,
            revision=revision,
            bars=self._read_bars(bus, dev, func),
        )
        self._devices[addr] = device

        # Recurse into additional functions of a multi-function device
        if func == 0:
            header_type = config_read8(bus, dev, func, 0x0E)
            if header_type & 0x80:
                for f in range(1, 8):
                    self._probe(bus, dev, f)

        return device

    # ── Driver registration ───────────────────────────────────────────────────

    def register_driver(
        self,
        driver: type[PCIDriver],
        *,
        vendor: int | None = None,
        device: int | None = None,
        class_code: PCIClass | None = None,
    ) -> None:
        if vendor is not None and device is not None:
            self._by_id[(vendor, device)] = driver
        elif vendor is not None:
            self._by_vendor[vendor] = driver
        elif class_code is not None:
            self._by_class[class_code] = driver
        else:
            raise ValueError("Provide at least one of: vendor+device, vendor, class_code")

    def _find_driver(self, dev: PCIDevice) -> type[PCIDriver] | None:
        return (
            self._by_id.get((dev.vendor_id, dev.device_id))
            or self._by_vendor.get(dev.vendor_id)
            or self._by_class.get(dev.class_code)
        )

    def bind_drivers(self) -> None:
        for dev in self._devices.values():
            cls = self._find_driver(dev)
            if cls:
                drv = cls()
                if drv.probe(dev):
                    dev.driver = drv

    # ── Iteration / lookup ────────────────────────────────────────────────────

    def __iter__(self) -> Iterator[PCIDevice]:
        return iter(self._devices.values())

    def __len__(self) -> int:
        return len(self._devices)

    def find_by_class(self, cls: PCIClass) -> list[PCIDevice]:
        return [d for d in self._devices.values() if d.class_code == cls]

    def find_by_id(self, vendor: int, device: int) -> list[PCIDevice]:
        return [d for d in self._devices.values()
                if d.vendor_id == vendor and d.device_id == device]


# Module-level singleton
bus = PCIBus()
