"""
kernel.drivers.display.ramfb — QEMU ramfb framebuffer (arm64 virt).

When QEMU is started with ``-device ramfb``, it exposes a fw_cfg item
``etc/ramfb`` that the guest writes to once at boot, telling QEMU where
the framebuffer lives in guest RAM and what its dimensions are. After
that, QEMU continuously samples the buffer and presents it on the host
display surface (e.g. SDL).

This is the simplest possible graphics path on arm64: no MMIO registers,
no virtqueues, just a flat XRGB8888 buffer that QEMU reads. It is exactly
what we need to bootstrap the GUI subsystem.
"""

import _hal
import kernel.log as log
from kernel.drivers.display import fwcfg


# DRM fourcc 'XR24' = XRGB8888, matching the existing Framebuffer pixel layout.
DRM_FORMAT_XR24 = 0x34325258


def _build_cfg_blob(addr: int, fourcc: int,
                    width: int, height: int, stride: int) -> bytes:
    """Build the 28-byte RAMFBCfg blob (all fields big-endian)."""
    out = bytearray(28)
    out[0:8]   = addr.to_bytes(8, "big")
    out[8:12]  = fourcc.to_bytes(4, "big")
    out[12:16] = (0).to_bytes(4, "big")
    out[16:20] = width.to_bytes(4, "big")
    out[20:24] = height.to_bytes(4, "big")
    out[24:28] = stride.to_bytes(4, "big")
    return bytes(out)


def setup(width: int = 1024, height: int = 768) -> dict | None:
    """Probe fw_cfg for ``etc/ramfb`` and configure a framebuffer.

    Returns an ``fb_info`` dict shaped like the multiboot2 framebuffer
    descriptor on x86 (so :class:`kernel.display.framebuffer.Framebuffer`
    can consume it directly), or ``None`` if ramfb is unavailable.
    """
    sig = fwcfg.signature()
    if sig != b"QEMU":
        log.info(f"ramfb: fw_cfg signature mismatch ({sig!r}); skipping")
        return None

    files = fwcfg.list_files()
    entry = files.get("etc/ramfb")
    if entry == None:
        log.info("ramfb: etc/ramfb not present (start QEMU with `-device ramfb`)")
        return None
    _size, selector = entry

    bpp     = 32
    stride  = width * (bpp // 8)
    fb_size = stride * height
    fb_phys = _hal.dma_alloc(fb_size)
    log.info(f"ramfb: allocated {fb_size}-byte framebuffer at {fb_phys:#x}")

    cfg = _build_cfg_blob(fb_phys, DRM_FORMAT_XR24, width, height, stride)
    if not fwcfg.write_item(selector, cfg):
        log.info("ramfb: fw_cfg DMA WRITE failed")
        return None

    log.info(f"ramfb: {width}x{height}x{bpp} ready")
    return {
        "phys_addr": fb_phys,
        "pitch":     stride,
        "width":     width,
        "height":    height,
        "bpp":       bpp,
        "type":      1,  # 1 = direct RGB (matches multiboot2 fb type)
    }
