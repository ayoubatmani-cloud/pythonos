"""sdl2.render — Software-renderer subset of PySDL2.

In v0 a :class:`SDL_Renderer` is just a thin wrapper around the window's
back-buffer surface; everything is drawn in pure software via the
existing :mod:`sdl2.surface` helpers and presented by blitting through
``SDL_UpdateWindowSurface``. :class:`SDL_Texture` is an alias for
:class:`SDL_Surface` — we have no GPU. This is enough to run the
sprite-blit corpus item.
"""

from kernel.gui.sdl2.surface import (
    SDL_Surface,
    SDL_Rect,
    SDL_FillRect,
    SDL_BlitSurface,
)
from kernel.gui.sdl2.video import SDL_UpdateWindowSurface


SDL_RENDERER_SOFTWARE      = 0x00000001
SDL_RENDERER_ACCELERATED   = 0x00000002
SDL_RENDERER_PRESENTVSYNC  = 0x00000004
SDL_RENDERER_TARGETTEXTURE = 0x00000008


class SDL_Renderer:
    def __init__(self, window) -> None:
        self.window = window
        self.draw_r = 0
        self.draw_g = 0
        self.draw_b = 0
        self.draw_a = 255

    @property
    def contents(self):
        return self

    @property
    def _surface(self):
        return self.window._surface


# In v0 a Texture *is* a Surface. PySDL2 patterns like
# ``texture.contents.format`` work because SDL_Surface already exposes
# .contents and .format.
SDL_Texture = SDL_Surface


# ── Public API ──────────────────────────────────────────────────────────────

def SDL_CreateRenderer(window, index: int = -1, flags: int = 0):
    return SDL_Renderer(window.contents if hasattr(window, "contents") else window)


def SDL_DestroyRenderer(renderer) -> None:
    pass


def SDL_SetRenderDrawColor(renderer, r: int, g: int, b: int, a: int = 255) -> int:
    R = renderer.contents if hasattr(renderer, "contents") else renderer
    R.draw_r, R.draw_g, R.draw_b, R.draw_a = r & 0xFF, g & 0xFF, b & 0xFF, a & 0xFF
    return 0


def _draw_color_xrgb(R) -> int:
    return (R.draw_r << 16) | (R.draw_g << 8) | R.draw_b


def SDL_RenderClear(renderer) -> int:
    R = renderer.contents if hasattr(renderer, "contents") else renderer
    SDL_FillRect(R._surface, None, _draw_color_xrgb(R))
    return 0


def SDL_RenderFillRect(renderer, rect) -> int:
    R = renderer.contents if hasattr(renderer, "contents") else renderer
    SDL_FillRect(R._surface, rect, _draw_color_xrgb(R))
    return 0


def SDL_RenderDrawRect(renderer, rect) -> int:
    """Outline a rect (single-pixel border) in the current draw color."""
    R = renderer.contents if hasattr(renderer, "contents") else renderer
    if rect == None:
        return 0
    r = rect.contents if hasattr(rect, "contents") else rect
    color = _draw_color_xrgb(R)
    s = R._surface
    s._fill_rect(r.x,         r.y,         r.w, 1, color)   # top
    s._fill_rect(r.x,         r.y + r.h - 1, r.w, 1, color) # bottom
    s._fill_rect(r.x,         r.y,         1, r.h, color)   # left
    s._fill_rect(r.x + r.w - 1, r.y,       1, r.h, color)   # right
    return 0


def SDL_RenderCopy(renderer, texture, src_rect, dst_rect) -> int:
    """Blit `texture` (an SDL_Surface) onto the renderer's surface.

    For v0 we honour the destination position but ignore src_rect (which
    PySDL2 typically passes None for sprite blits). Stretching is not
    supported — texture is copied 1:1.
    """
    R = renderer.contents if hasattr(renderer, "contents") else renderer
    SDL_BlitSurface(texture, src_rect, R._surface, dst_rect)
    return 0


def SDL_RenderPresent(renderer) -> None:
    """Push the renderer's surface to the live framebuffer."""
    R = renderer.contents if hasattr(renderer, "contents") else renderer
    SDL_UpdateWindowSurface(R.window)


def SDL_CreateTextureFromSurface(renderer, surface):
    """In our software model a texture is just the source surface."""
    return surface.contents if hasattr(surface, "contents") else surface


def SDL_DestroyTexture(texture) -> None:
    pass
