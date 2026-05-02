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


def load(path: str) -> SDL_Surface:
    """Decode an image file at ``path`` into an :class:`SDL_Surface`.

    Raises :class:`NotImplementedError` for formats whose decoder is
    not yet shipped in the kernel.
    """
    p = path.decode() if isinstance(path, (bytes, bytearray)) else str(path)
    with open(p, "rb") as f:
        head = f.read(16)
    fmt = _detect(head)
    if fmt == "bmp":
        return SDL_LoadBMP(p)
    if fmt == "ppm":
        from kernel.gui.image.ppm import load_ppm
        return load_ppm(p)
    if fmt == "png":
        raise NotImplementedError(
            "PNG: decoder needs zlib or pure-Python inflate "
            "(GUI Phase 6 follow-up)")
    if fmt == "jpeg":
        raise NotImplementedError(
            "JPEG: decoder needs Huffman+DCT pure-Python implementation "
            "(GUI Phase 6 follow-up)")
    raise ValueError(f"image.load: unsupported format for {p}")
