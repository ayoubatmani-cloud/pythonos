"""sdl2.surface — :class:`SDL_Surface`, :func:`SDL_FillRect`, color helpers.

A :class:`SDL_Surface` here is a thin Python wrapper around a bytearray
holding XRGB8888 pixels. Drawing is done by mutating that bytearray;
:func:`SDL_UpdateWindowSurface` copies it to the framebuffer.

The .contents shim emulates the PySDL2 idiom where ``surface.contents``
is the ctypes-dereferenced struct — for us it's just ``self``.
"""

from dataclasses import dataclass


# ── PixelFormat (minimal) ───────────────────────────────────────────────────

class SDL_PixelFormat:
    """All we expose is BitsPerPixel — that's what SDL_MapRGB looks at."""
    def __init__(self, bpp: int = 32) -> None:
        self.BitsPerPixel = bpp
        self.format = 0x16462004  # SDL_PIXELFORMAT_XRGB8888 — informational

    @property
    def contents(self):  # PySDL2 ctypes-style accessor
        return self


# ── Geometry types ──────────────────────────────────────────────────────────

@dataclass
class SDL_Rect:
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


@dataclass
class SDL_Point:
    x: int = 0
    y: int = 0


@dataclass
class SDL_Color:
    r: int = 0
    g: int = 0
    b: int = 0
    a: int = 255


# ── Surface ─────────────────────────────────────────────────────────────────

class SDL_Surface:
    """XRGB8888 software surface."""

    def __init__(self, w: int, h: int) -> None:
        self.w = w
        self.h = h
        self.pitch = w * 4
        self.pixels = bytearray(w * h * 4)
        self.format = SDL_PixelFormat(32)

    @property
    def contents(self):
        return self

    # Internal pixel access (LE-stored XRGB)
    def _put(self, x: int, y: int, color: int) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            o = (y * self.w + x) * 4
            self.pixels[o]     =  color        & 0xFF  # B
            self.pixels[o + 1] = (color >>  8) & 0xFF  # G
            self.pixels[o + 2] = (color >> 16) & 0xFF  # R
            self.pixels[o + 3] = 0xFF                  # X

    def _fill_rect(self, x: int, y: int, w: int, h: int, color: int) -> None:
        x1 = max(0, x); y1 = max(0, y)
        x2 = min(self.w, x + w); y2 = min(self.h, y + h)
        b =  color        & 0xFF
        g = (color >>  8) & 0xFF
        r = (color >> 16) & 0xFF
        pixel = bytes((b, g, r, 0xFF))
        for row in range(y1, y2):
            o = (row * self.w + x1) * 4
            self.pixels[o : o + (x2 - x1) * 4] = pixel * (x2 - x1)

    def _blit(self, src: "SDL_Surface", dst_x: int, dst_y: int) -> None:
        for sy in range(src.h):
            dy = dst_y + sy
            if dy < 0 or dy >= self.h:
                continue
            so = sy * src.w * 4
            do = (dy * self.w + dst_x) * 4
            n = min(src.w, self.w - dst_x) * 4
            if n <= 0:
                continue
            self.pixels[do:do + n] = src.pixels[so:so + n]


# ── Public API ──────────────────────────────────────────────────────────────

def SDL_MapRGB(fmt, r: int, g: int, b: int) -> int:
    """Pack an RGB triple to a 32-bit XRGB8888 pixel value."""
    return ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


def SDL_MapRGBA(fmt, r: int, g: int, b: int, a: int) -> int:
    """For our XRGB surface alpha is ignored, but accepted for API parity."""
    return ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


def SDL_FillRect(surface, rect, color: int) -> int:
    """Fill ``rect`` (or whole surface if rect == None) with ``color``."""
    if isinstance(surface, SDL_Surface):
        s = surface
    elif hasattr(surface, "contents"):
        s = surface.contents
    else:
        s = surface
    if rect == None:
        s._fill_rect(0, 0, s.w, s.h, color)
    else:
        r = rect.contents if hasattr(rect, "contents") else rect
        s._fill_rect(r.x, r.y, r.w, r.h, color)
    return 0


def SDL_BlitSurface(src, src_rect, dst, dst_rect) -> int:
    s_src = src.contents if hasattr(src, "contents") else src
    s_dst = dst.contents if hasattr(dst, "contents") else dst
    dx = dst_rect.x if dst_rect != None else 0
    dy = dst_rect.y if dst_rect != None else 0
    s_dst._blit(s_src, dx, dy)
    return 0


def SDL_FreeSurface(surface) -> None:
    pass  # GC handles it


def SDL_LoadBMP(path: bytes | str):
    """Minimal BMP loader sufficient for the compatibility corpus.

    Supports 24- and 32-bit uncompressed BMP only — the common ones."""
    p = path.decode() if isinstance(path, (bytes, bytearray)) else str(path)
    with open(p, "rb") as f:
        data = f.read()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError(f"SDL_LoadBMP: {p}: not a BMP file")
    px_off = int.from_bytes(data[10:14], "little")
    width  = int.from_bytes(data[18:22], "little", signed=True)
    height = int.from_bytes(data[22:26], "little", signed=True)
    bpp    = int.from_bytes(data[28:30], "little")
    if bpp not in (24, 32):
        raise ValueError(f"SDL_LoadBMP: {p}: unsupported bpp={bpp}")
    flip = height > 0
    h = abs(height)
    s = SDL_Surface(width, h)
    row_bytes = (width * bpp // 8 + 3) & ~3   # 4-byte aligned
    for row in range(h):
        src_row = h - 1 - row if flip else row
        sy = src_row
        src_off = px_off + sy * row_bytes
        dst_off = row * width * 4
        for x in range(width):
            so = src_off + x * (bpp // 8)
            b = data[so]
            g = data[so + 1]
            r = data[so + 2]
            s.pixels[dst_off + x * 4]     = b
            s.pixels[dst_off + x * 4 + 1] = g
            s.pixels[dst_off + x * 4 + 2] = r
            s.pixels[dst_off + x * 4 + 3] = 0xFF
    return s
