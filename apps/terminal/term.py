"""apps.terminal.term — REPL inside a compositor window.

The window owns:
    * a ``TerminalView`` that maintains a text grid (cols x rows derived
      from the window size and the 8x16 bitmap font) and exposes
      ``write(text)`` / ``read_char()`` callables that match the
      :class:`kernel.shell.Shell` constructor signature.
    * an event handler that turns :data:`kernel.gui.input.Event` records
      into single characters fed to the shell (printable text from
      ``ev.text``, plus mapped keys for Enter / Backspace / Tab).

Linenoise is intentionally not wired here — the window-side input is
char-at-a-time and goes through ``Shell._read_line_fallback`` which
already handles backspace + tab completion.
"""

import asyncio

from kernel.display.font import GLYPH_W, GLYPH_H
from kernel.gui.compositor import compositor, CompositorWindow
from kernel.gui import input as _gui_input
from kernel.gui.sdl2.surface import SDL_FillRect
from kernel.shell import Shell
from apps import registry


_FG = 0xCCCCCC
_BG = 0x101010
_CURSOR_FG = 0xFFFFFF


class TerminalView:
    def __init__(self, window: CompositorWindow) -> None:
        self.win = window
        self.cols = max(1, window.w // GLYPH_W)
        self.rows = max(1, window.h // GLYPH_H)
        self.cur_x = 0
        self.cur_y = 0
        self._input_q: asyncio.Queue = asyncio.Queue()
        # Paint background once.
        SDL_FillRect(window.surface, None, _BG)
        window.dirty = True

    # ── Drawing ─────────────────────────────────────────────────────────

    def _scroll_up(self) -> None:
        s = self.win.surface
        row_pixels = s.w * 4 * GLYPH_H
        # Shift everything but the last GLYPH_H rows up by one row.
        s.pixels[0 : len(s.pixels) - row_pixels] = s.pixels[row_pixels:]
        # Clear the new bottom row.
        b =  _BG        & 0xFF
        g = (_BG >>  8) & 0xFF
        r = (_BG >> 16) & 0xFF
        bottom_start = len(s.pixels) - row_pixels
        clear = bytes((b, g, r, 0xFF)) * (s.w * GLYPH_H)
        s.pixels[bottom_start:bottom_start + len(clear)] = clear

    def _draw_glyph_at(self, col: int, row: int, ch: str) -> None:
        self.win.surface.draw_char(col * GLYPH_W, row * GLYPH_H,
                                    ch, fg=_FG, bg=_BG)

    def _erase_glyph_at(self, col: int, row: int) -> None:
        x0 = col * GLYPH_W
        y0 = row * GLYPH_H
        self.win.surface._fill_rect(x0, y0, GLYPH_W, GLYPH_H, _BG)

    # ── Public callables (match Shell's read_char/write contract) ───────

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
            elif ord(ch) >= 32 and ord(ch) < 127:
                if self.cur_x >= self.cols:
                    self.cur_x = 0
                    self.cur_y += 1
                self._draw_glyph_at(self.cur_x, self.cur_y, ch)
                self.cur_x += 1
            # else: ignore other control bytes (esc sequences, tab, …)

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


# ── App entry ───────────────────────────────────────────────────────────

async def main(*args, **kwargs) -> None:
    win = CompositorWindow("Terminal", x=60, y=60, w=640, h=400)
    compositor.add_window(win)
    view = TerminalView(win)
    win.set_event_handler(view.on_event)

    shell = Shell(read_char=view.read_char, write=view.write)
    try:
        await shell.run()
    finally:
        win.close()


registry.register(
    name="terminal",
    description="Python REPL in a window",
    entry=main,
)
