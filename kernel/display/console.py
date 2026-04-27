"""
kernel.display.console — Scrolling text console on the framebuffer.

Wraps Framebuffer with a cursor, line buffer, and scroll.
Also mirrors output to COM1 serial so QEMU -nographic works.
"""


from kernel.display.framebuffer import Framebuffer, BLACK, WHITE, GREEN, DARK
from kernel.display.font import GLYPH_W, GLYPH_H
import kernel.log as log


class Console:
    MARGIN = 4   # pixels

    def __init__(self, fb: Framebuffer,
                 fg: int = GREEN, bg: int = DARK) -> None:
        self._fb   = fb
        self._fg   = fg
        self._bg   = bg
        self._cols = (fb.width  - self.MARGIN * 2) // GLYPH_W
        self._rows = (fb.height - self.MARGIN * 2) // GLYPH_H
        self._cx   = 0   # cursor column
        self._cy   = 0   # cursor row
        self._lines: list[str] = [""] * self._rows
        fb.fill(bg)

    @property
    def cols(self) -> int: return self._cols
    @property
    def rows(self) -> int: return self._rows

    def write(self, text: str) -> None:
        log._serial(text)  # mirror to serial
        for ch in text:
            if ch == '\n':
                self._newline()
            elif ch == '\r':
                self._cx = 0
            elif ch == '\b':
                if self._cx > 0:
                    self._cx -= 1
                    self._draw_char(self._cx, self._cy, ' ')
                    self._lines[self._cy] = self._lines[self._cy][:-1]
            else:
                self._draw_char(self._cx, self._cy, ch)
                if self._cx < len(self._lines[self._cy]):
                    self._lines[self._cy] = (
                        self._lines[self._cy][:self._cx] + ch +
                        self._lines[self._cy][self._cx + 1:]
                    )
                else:
                    self._lines[self._cy] += ch
                self._cx += 1
                if self._cx >= self._cols:
                    self._newline()

    def writeln(self, text: str = "") -> None:
        self.write(text + "\n")

    def _newline(self) -> None:
        self._cx = 0
        self._cy += 1
        if self._cy >= self._rows:
            self._scroll()
            self._cy = self._rows - 1

    def _scroll(self) -> None:
        self._lines = self._lines[1:] + [""]
        self._redraw()

    def _redraw(self) -> None:
        self._fb.fill(self._bg)
        for row, line in enumerate(self._lines):
            for col, ch in enumerate(line):
                self._draw_char(col, row, ch)

    def _draw_char(self, col: int, row: int, ch: str) -> None:
        px = self.MARGIN + col * GLYPH_W
        py = self.MARGIN + row * GLYPH_H
        self._fb.draw_char(px, py, ch, fg=self._fg, bg=self._bg)

    def clear(self) -> None:
        self._lines = [""] * self._rows
        self._cx = self._cy = 0
        self._fb.fill(self._bg)


# Module-level singleton — set after framebuffer init
console: Console | None = None
