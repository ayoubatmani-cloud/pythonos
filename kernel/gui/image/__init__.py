"""
kernel.gui.image — Image decoding for PythonOS apps (image viewer, etc.).

v0 supports the formats whose decoders fit in pure Python without needing
``zlib`` or libpng/libjpeg in the kernel build:

    BMP — uncompressed 24/32-bit  (decoder is in kernel.gui.sdl2.surface)
    PPM — Netpbm P6 binary RGB

PNG and JPEG are stubbed; they need either ``zlib`` linked into the kernel
or a pure-Python inflate (PNG) / Huffman+DCT (JPEG) decoder. Tracked as
follow-up beads.
"""

from kernel.gui.sdl2.surface import SDL_Surface, SDL_LoadBMP


def _detect(magic: bytes) -> str:
    if magic.startswith(b"BM"):
        return "bmp"
    if magic.startswith(b"P6\n") or magic.startswith(b"P6 ") or magic[:2] == b"P6":
        return "ppm"
    if magic.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if magic.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return "unknown"


def load_bytes(data: bytes) -> SDL_Surface:
    """Decode an image from a byte string into an :class:`SDL_Surface`.

    The kernel uses this path because libc's ``open()`` returns ENOSYS;
    callers read the file through the VFS and pass the bytes here.
    """
    fmt = _detect(data[:16])
    if fmt == "png":
        from kernel.gui.image.png import decode_png
        return decode_png(data)
    if fmt == "ppm":
        from kernel.gui.image.ppm import decode_ppm
        return decode_ppm(data)
    if fmt == "bmp":
        from kernel.gui.image.bmp import decode_bmp
        return decode_bmp(data)
    if fmt == "jpeg":
        raise NotImplementedError(
            "JPEG: decoder needs Huffman+DCT pure-Python implementation "
            "(GUI Phase 6 follow-up)")
    raise ValueError("image.load_bytes: unsupported format")


def load(path: str) -> SDL_Surface:
    """File-based wrapper. Works on hosts where ``open()`` is wired up;
    inside the bare-metal kernel callers should use :func:`load_bytes`
    after reading via the VFS."""
    p = path.decode() if isinstance(path, (bytes, bytearray)) else str(path)
    with open(p, "rb") as f:
        data = f.read()
    return load_bytes(data)
