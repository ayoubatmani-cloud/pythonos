"""sdl2.sdlttf — Text rendering compat layer.

Real SDL_ttf is a libfreetype wrapper. Our v0 implementation backs
TTF_RenderText_Blended with the existing 8x16 bitmap font in
``kernel.display.font`` — the resulting :class:`SDL_Surface` has the
right shape and contents for the corpus, even if the "size" parameter
is honoured only as a coarse line-height multiplier.

This is intentionally minimal:
    TTF_Init / TTF_Quit             — bookkeeping
    TTF_OpenFont                    — returns an opaque Font object
    TTF_RenderText_Blended          — returns an SDL_Surface with the text
    TTF_RenderText_Solid            — alias for Blended (no alpha distinction)
    TTF_SizeText                    — ``(w, h)`` pixel size of a string
    TTF_CloseFont                   — bookkeeping
"""

from kernel.display.font import GLYPH_W, GLYPH_H
from kernel.gui.sdl2.surface import SDL_Surface


_initialized = False


def TTF_Init() -> int:
    global _initialized
    _initialized = True
    return 0


def TTF_Quit() -> None:
    global _initialized
    _initialized = False


def TTF_WasInit() -> int:
    return 1 if _initialized else 0


class TTF_Font:
    """Opaque font handle. The bundled bitmap font is fixed-size, so
    ``size`` only changes line height (rendered by drawing each glyph
    centred in a size-tall row)."""

    def __init__(self, path: str, size: int) -> None:
        self.path = path
        self.size = size
        self.line_height = max(GLYPH_H, size)
        self.advance = GLYPH_W

    @property
    def contents(self):
        return self


def TTF_OpenFont(path, size: int):
    if isinstance(path, (bytes, bytearray)):
        path = path.decode("utf-8", errors="replace")
    return TTF_Font(str(path), int(size))


def TTF_CloseFont(font) -> None:
    pass


def _color_to_int(color) -> int:
    if hasattr(color, "contents"):
        color = color.contents
    if hasattr(color, "r"):
        return ((color.r & 0xFF) << 16) | ((color.g & 0xFF) << 8) | (color.b & 0xFF)
    if isinstance(color, (tuple, list)) and len(color) >= 3:
        return ((color[0] & 0xFF) << 16) | ((color[1] & 0xFF) << 8) | (color[2] & 0xFF)
    if isinstance(color, int):
        return color
    return 0xFFFFFF


def _render(font, text: str, fg) -> SDL_Surface:
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", errors="replace")
    f = font.contents if hasattr(font, "contents") else font
    fg_int = _color_to_int(fg)
    w = max(f.advance * len(text), 1)
    h = f.line_height
    s = SDL_Surface(w, h)
    # Centre the glyph baseline vertically inside the line.
    y = max(0, (h - GLYPH_H) // 2)
    s.draw_text(0, y, text, fg=fg_int, bg=None)
    return s


def TTF_RenderText_Blended(font, text, fg):
    return _render(font, text, fg)


def TTF_RenderText_Solid(font, text, fg):
    return _render(font, text, fg)


def TTF_SizeText(font, text) -> tuple[int, int]:
    f = font.contents if hasattr(font, "contents") else font
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", errors="replace")
    return (f.advance * len(text), f.line_height)
