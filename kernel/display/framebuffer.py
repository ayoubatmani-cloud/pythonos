"""
kernel.display.framebuffer — Linear framebuffer rendering.

Writes directly to the physical framebuffer via _hal.mmio_write32().
Supports 32-bit (XRGB8888) and 24-bit colour modes.

Coordinate system: (0,0) = top-left.
"""


from dataclasses import dataclass
from kernel.hal.io import mmio_write32, mmio_read32
from kernel.display.font import get_glyph, GLYPH_W, GLYPH_H


# ── Colour helpers ────────────────────────────────────────────────────────────

def rgb(r: int, g: int, b: int) -> int:
    return (r << 16) | (g << 8) | b

BLACK   = rgb(0,   0,   0)
WHITE   = rgb(255, 255, 255)
GREEN   = rgb(0,   255, 0)
RED     = rgb(255, 0,   0)
BLUE    = rgb(0,   0,   255)
YELLOW  = rgb(255, 255, 0)
CYAN    = rgb(0,   255, 255)
MAGENTA = rgb(255, 0,   255)
GREY    = rgb(128, 128, 128)
DARK    = rgb(20,  20,  20)


# ── Surface — off-screen pixel buffer ────────────────────────────────────────

class Surface:
    """
    Software-rendered pixel buffer. Blit to Framebuffer when ready.
    Backed by a Python bytearray (no MMIO until blit).
    """

    def __init__(self, width: int, height: int, bg: int = BLACK) -> None:
        self.width  = width
        self.height = height
        self._buf   = bytearray(width * height * 4)
        if bg:
            self.fill(bg)

    def _offset(self, x: int, y: int) -> int:
        return (y * self.width + x) * 4

    def put_pixel(self, x: int, y: int, colour: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            o = self._offset(x, y)
            self._buf[o]     =  colour        & 0xFF  # B
            self._buf[o + 1] = (colour >> 8)  & 0xFF  # G
            self._buf[o + 2] = (colour >> 16) & 0xFF  # R
            self._buf[o + 3] = 0xFF                   # X

    def get_pixel(self, x: int, y: int) -> int:
        o = self._offset(x, y)
        return (self._buf[o + 2] << 16) | (self._buf[o + 1] << 8) | self._buf[o]

    def fill(self, colour: int) -> None:
        b = colour & 0xFF
        g = (colour >> 8)  & 0xFF
        r = (colour >> 16) & 0xFF
        pixel = bytes([b, g, r, 0xFF])
        self._buf[:] = pixel * (self.width * self.height)

    def fill_rect(self, x: int, y: int, w: int, h: int, colour: int) -> None:
        x1 = max(0, x);       y1 = max(0, y)
        x2 = min(self.width, x + w)
        y2 = min(self.height, y + h)
        b = colour & 0xFF
        g = (colour >> 8)  & 0xFF
        r = (colour >> 16) & 0xFF
        pixel = bytes([b, g, r, 0xFF])
        for row in range(y1, y2):
            o = (row * self.width + x1) * 4
            self._buf[o:o + (x2 - x1) * 4] = pixel * (x2 - x1)

    def draw_char(self, x: int, y: int, char: str,
                  fg: int = WHITE, bg: int | None = None) -> None:
        glyph = get_glyph(char)
        for row, byte in enumerate(glyph):
            for col in range(8):
                if byte & (0x80 >> col):
                    self.put_pixel(x + col, y + row, fg)
                elif bg is not None:
                    self.put_pixel(x + col, y + row, bg)

    def draw_text(self, x: int, y: int, text: str,
                  fg: int = WHITE, bg: int | None = None) -> int:
        """Draw string; returns x position after last character."""
        cx = x
        for ch in text:
            if ch == '\n':
                y += GLYPH_H
                cx = x
            else:
                self.draw_char(cx, y, ch, fg, bg)
                cx += GLYPH_W
        return cx


# ── Framebuffer ───────────────────────────────────────────────────────────────

class Framebuffer:
    """
    Direct-write linear framebuffer.

    All pixel writes go to physical memory via mmio_write32.
    For animated content, render to a Surface first and blit.
    """

    def __init__(self, info: dict) -> None:
        self.phys   = info["phys_addr"]
        self.pitch  = info["pitch"]
        self.width  = info["width"]
        self.height = info["height"]
        self.bpp    = info["bpp"]
        self._bytes_per_pixel = self.bpp // 8

    def _pixel_addr(self, x: int, y: int) -> int:
        return self.phys + y * self.pitch + x * self._bytes_per_pixel

    def put_pixel(self, x: int, y: int, colour: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            mmio_write32(self._pixel_addr(x, y), colour)

    def fill(self, colour: int) -> None:
        for y in range(self.height):
            row_base = self.phys + y * self.pitch
            for x in range(self.width):
                mmio_write32(row_base + x * self._bytes_per_pixel, colour)

    def fill_rect(self, x: int, y: int, w: int, h: int, colour: int) -> None:
        for row in range(max(0, y), min(self.height, y + h)):
            row_base = self.phys + row * self.pitch
            for col in range(max(0, x), min(self.width, x + w)):
                mmio_write32(row_base + col * self._bytes_per_pixel, colour)

    def blit(self, surface: Surface, dst_x: int = 0, dst_y: int = 0) -> None:
        """Copy surface pixel buffer to framebuffer."""
        bpp = self._bytes_per_pixel
        for sy in range(surface.height):
            dy = dst_y + sy
            if dy < 0 or dy >= self.height:
                continue
            fb_row  = self.phys + dy * self.pitch + dst_x * bpp
            src_off = sy * surface.width * 4
            for sx in range(surface.width):
                dx = dst_x + sx
                if dx < 0 or dx >= self.width:
                    continue
                so = src_off + sx * 4
                pixel = (
                    (surface._buf[so + 2] << 16) |
                    (surface._buf[so + 1] << 8)  |
                     surface._buf[so]
                )
                mmio_write32(fb_row + sx * bpp, pixel)

    def draw_char(self, x: int, y: int, char: str,
                  fg: int = WHITE, bg: int | None = None) -> None:
        glyph = get_glyph(char)
        for row, byte in enumerate(glyph):
            for col in range(8):
                px = x + col
                py = y + row
                if byte & (0x80 >> col):
                    self.put_pixel(px, py, fg)
                elif bg is not None:
                    self.put_pixel(px, py, bg)

    def draw_text(self, x: int, y: int, text: str,
                  fg: int = WHITE, bg: int | None = None) -> tuple[int, int]:
        """Draw string; returns (x, y) position after last character."""
        cx, cy = x, y
        for ch in text:
            if ch == '\n':
                cy += GLYPH_H
                cx = x
            else:
                self.draw_char(cx, cy, ch, fg, bg)
                cx += GLYPH_W
        return cx, cy


# Module-level singleton — set by kernel.boot() when fb info is available
fb: Framebuffer | None = None
