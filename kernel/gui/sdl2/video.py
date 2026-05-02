"""sdl2.video — Window creation + surface presentation.

In v0 there is one global "window" which is the full framebuffer; the
Window's surface is an off-screen XRGB8888 buffer that
:func:`SDL_UpdateWindowSurface` blits into the live framebuffer. After
the Phase 5 compositor lands, multiple windows compose properly.
"""

from kernel.gui.sdl2.surface import SDL_Surface


SDL_WINDOWPOS_UNDEFINED = 0x1FFF0000
SDL_WINDOWPOS_CENTERED  = 0x2FFF0000

SDL_WINDOW_SHOWN     = 0x00000004
SDL_WINDOW_HIDDEN    = 0x00000008
SDL_WINDOW_RESIZABLE = 0x00000020


class SDL_Window:
    def __init__(self, title: str, x: int, y: int,
                 w: int, h: int, flags: int = SDL_WINDOW_SHOWN) -> None:
        self.title = title
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.flags = flags
        self._surface = SDL_Surface(w, h)

    @property
    def contents(self):
        return self


def SDL_CreateWindow(title, x: int, y: int,
                     w: int, h: int, flags: int = SDL_WINDOW_SHOWN):
    if isinstance(title, (bytes, bytearray)):
        title = title.decode("utf-8", errors="replace")
    return SDL_Window(title, x, y, w, h, flags)


def SDL_DestroyWindow(window) -> None:
    pass  # GC handles it


def SDL_GetWindowSurface(window):
    w = window.contents if hasattr(window, "contents") else window
    return w._surface


def SDL_UpdateWindowSurface(window) -> int:
    """Blit the window's off-screen surface to the live framebuffer."""
    w = window.contents if hasattr(window, "contents") else window
    from kernel.display.framebuffer import fb
    if fb is None:
        return -1
    s = w._surface
    # Centre the window on the framebuffer if it fits, else clip to top-left.
    dst_x = max(0, (fb.width  - s.w) // 2)
    dst_y = max(0, (fb.height - s.h) // 2)
    # Direct row copy: each surface row is 4 bytes/pixel; pitch == 4*w.
    for sy in range(min(s.h, fb.height - dst_y)):
        for sx in range(min(s.w, fb.width - dst_x)):
            o = (sy * s.w + sx) * 4
            pix = (s.pixels[o + 2] << 16) | (s.pixels[o + 1] << 8) | s.pixels[o]
            fb.put_pixel(dst_x + sx, dst_y + sy, pix)
    return 0


def SDL_SetWindowTitle(window, title) -> None:
    w = window.contents if hasattr(window, "contents") else window
    w.title = title.decode("utf-8") if isinstance(title, (bytes, bytearray)) else str(title)
