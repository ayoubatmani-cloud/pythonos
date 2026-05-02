"""
kernel.drivers.display — Display device drivers (graphics output).

x86 framebuffer is delivered by GRUB via the multiboot2 framebuffer tag
(see src/boot/fb.c), so x86 needs no driver here. arm64 has no firmware
to negotiate one, so :mod:`ramfb` allocates a buffer and posts it to
QEMU via fw_cfg when ``-device ramfb`` is present.
"""
