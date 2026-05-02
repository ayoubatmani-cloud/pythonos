"""apps._textwin — Shared text-grid window for terminal-style apps.

Wraps a :class:`kernel.gui.compositor.CompositorWindow` in a
fixed-pitch text grid backed by the bundled 8x16 bitmap font, exposing
:meth:`write` (renders glyphs and advances the cursor) and
:meth:`read_char` (an async coroutine the host can ``await``).

Both the terminal and editor apps drive their host (Shell or Editor)
with this single class — neither needs to know about pixels.
"""

import asyncio

from kernel.display.font import GLYPH_W, GLYPH_H
from kernel.gui import input as _gui_input
from kernel.gui.compositor import CompositorWindow
from kernel.gui.sdl2.surface import SDL_FillRect


class TextWin:
    """A line-buffered text terminal inside a CompositorWindow."""

    def __init__(self, window: CompositorWindow,
                 fg: int = 0xCCCCCC, bg: int = 0x101010) -> None:
        self.win = window
        self.fg = fg
        self.bg = bg
        self.cols = max(1, window.w // GLYPH_W)
        self.rows = max(1, window.h // GLYPH_H)
        self.cur_x = 0
        self.cur_y = 0
        self._input_q: asyncio.Queue = asyncio.Queue()
        SDL_FillRect(window.surface, None, self.bg)
        window.dirty = True

    # ── Drawing ─────────────────────────────────────────────────────────

    def _scroll_up(self) -> None:
        s = self.win.surface
        row_pixels = s.w * 4 * GLYPH_H
        s.pixels[0 : len(s.pixels) - row_pixels] = s.pixels[row_pixels:]
        b =  self.bg        & 0xFF
        g = (self.bg >>  8) & 0xFF
        r = (self.bg >> 16) & 0xFF
        bottom_start = len(s.pixels) - row_pixels
        clear = bytes((b, g, r, 0xFF)) * (s.w * GLYPH_H)
        s.pixels[bottom_start:bottom_start + len(clear)] = clear

    def _draw_glyph_at(self, col: int, row: int, ch: str) -> None:
        self.win.surface.draw_char(col * GLYPH_W, row * GLYPH_H,
                                    ch, fg=self.fg, bg=self.bg)

    def _erase_glyph_at(self, col: int, row: int) -> None:
        self.win.surface._fill_rect(col * GLYPH_W, row * GLYPH_H,
                                     GLYPH_W, GLYPH_H, self.bg)

    def clear(self) -> None:
        SDL_FillRect(self.win.surface, None, self.bg)
        self.cur_x = 0
        self.cur_y = 0
        self.win.dirty = True

    # ── Public callables (Shell / Editor write+read_char contract) ──────

    def write(self, text: str) -> None:
        for ch in text:
            if ch == "\n":
                self.cur_x = 0
                self.cur_y += 1
            elif ch == "\r":
                self.cur_x = 0
            elif ch == "\b":
                if self.cur_x > 0:
                    self.cur_x -= 1
                    self._erase_glyph_at(self.cur_x, self.cur_y)
            elif ch == " ":
                self._draw_glyph_at(self.cur_x, self.cur_y, " ")
                self.cur_x += 1
            elif 32 <= ord(ch) < 127:
                if self.cur_x >= self.cols:
                    self.cur_x = 0
                    self.cur_y += 1
                self._draw_glyph_at(self.cur_x, self.cur_y, ch)
                self.cur_x += 1

            if self.cur_y >= self.rows:
                self._scroll_up()
                self.cur_y = self.rows - 1

        self.win.dirty = True

    async def read_char(self) -> str:
        return await self._input_q.get()

    # ── Event ingestion ─────────────────────────────────────────────────

    def on_event(self, ev) -> None:
        if ev.kind != _gui_input.KEY_DOWN:
            return
        if ev.code == _gui_input.KEY_ENTER:
            self._input_q.put_nowait("\n")
        elif ev.code == _gui_input.KEY_BACKSPACE:
            self._input_q.put_nowait("\b")
        elif ev.code == _gui_input.KEY_TAB:
            self._input_q.put_nowait("\t")
        elif ev.text:
            self._input_q.put_nowait(ev.text)
