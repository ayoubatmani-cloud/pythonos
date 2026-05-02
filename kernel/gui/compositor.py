"""
kernel.gui.compositor — Stacking window manager.

v0 surface:
    * One :class:`CompositorWindow` per app, holding an XRGB8888 surface.
    * Front-to-back z-order list; rear-most painted first.
    * Each window optionally gets a 16-pixel title bar.
    * Focus follows the topmost window; Tab/Shift-Tab cycles focus
      (mouse follow-up adds drag + click-to-focus).
    * Async draw task @ 30 fps blits every dirty window to the live
      framebuffer.

Apps register a CompositorWindow via :func:`Compositor.add_window`,
then either render directly into ``window.surface`` or, for SDL2
compatibility, point an ``sdl2.SDL_Window`` at the compositor window.
"""

import asyncio
import kernel.log as log
from kernel.display import framebuffer as _fb_mod
from kernel.display.font import GLYPH_W, GLYPH_H
from kernel.gui import input as _gui_input
from kernel.gui.sdl2.surface import SDL_Surface


# ── Title-bar geometry ──────────────────────────────────────────────────────

TITLE_BAR_H = 16
CHROME_BORDER = 1
CHROME_FOCUS_BG   = 0x224488
CHROME_UNFOCUS_BG = 0x303030
CHROME_FG         = 0xFFFFFF


# ── CompositorWindow ────────────────────────────────────────────────────────

class CompositorWindow:
    """One displayable window. Apps mutate ``surface`` then mark
    ``dirty = True`` to schedule a redraw."""

    def __init__(self, title: str, x: int, y: int, w: int, h: int,
                 chrome: bool = True) -> None:
        self.title  = title
        self.x      = x
        self.y      = y
        self.w      = w
        self.h      = h
        self.chrome = chrome
        self.surface = SDL_Surface(w, h)
        self.dirty   = True
        self.focused = False
        self._on_event = None  # callback fn(Event) — set by app
        self._closed   = False

    def set_event_handler(self, fn) -> None:
        self._on_event = fn

    def deliver(self, ev) -> None:
        if self._on_event:
            try:
                self._on_event(ev)
            except Exception:
                pass

    def close(self) -> None:
        self._closed = True


# ── Compositor ──────────────────────────────────────────────────────────────

class Compositor:
    """Singleton; one per system. Owns the input-routing task and the
    redraw task. v0 has no mouse so window placement is set by apps."""

    def __init__(self) -> None:
        self._windows: list[CompositorWindow] = []
        self._focus_idx = -1
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._tick_hz = 30
        self._desktop_bg = 0x202840   # deep-navy desktop

    # ── Window registry ─────────────────────────────────────────────────────

    def add_window(self, win: CompositorWindow) -> None:
        self._windows.append(win)
        if self._focus_idx < 0:
            self._focus_idx = 0
            win.focused = True
        win.dirty = True

    def remove_window(self, win: CompositorWindow) -> None:
        if win not in self._windows:
            return
        idx = self._windows.index(win)
        self._windows.remove(win)
        if idx == self._focus_idx and self._windows:
            self._focus_idx = min(self._focus_idx, len(self._windows) - 1)
            self._windows[self._focus_idx].focused = True
        elif not self._windows:
            self._focus_idx = -1

    def cycle_focus(self, direction: int = 1) -> None:
        if not self._windows:
            return
        if 0 <= self._focus_idx < len(self._windows):
            self._windows[self._focus_idx].focused = False
        self._focus_idx = (self._focus_idx + direction) % len(self._windows)
        self._windows[self._focus_idx].focused = True
        for w in self._windows:
            w.dirty = True

    @property
    def focused_window(self) -> CompositorWindow | None:
        if 0 <= self._focus_idx < len(self._windows):
            return self._windows[self._focus_idx]
        return None

    # ── Drawing ─────────────────────────────────────────────────────────────

    def _paint_chrome(self, win: CompositorWindow, fb) -> None:
        if not win.chrome:
            return
        bg = CHROME_FOCUS_BG if win.focused else CHROME_UNFOCUS_BG
        fb.fill_rect(win.x, win.y, win.w, TITLE_BAR_H, bg)
        title = win.title or ""
        if len(title) * GLYPH_W > win.w - 8:
            title = title[: max(1, (win.w - 8) // GLYPH_W)]
        fb.draw_text(win.x + 4, win.y + (TITLE_BAR_H - GLYPH_H) // 2,
                     title, fg=CHROME_FG, bg=bg)

    def _paint_window_body(self, win: CompositorWindow, fb) -> None:
        body_y = win.y + (TITLE_BAR_H if win.chrome else 0)
        s = win.surface
        for sy in range(min(s.h, fb.height - body_y)):
            fy = body_y + sy
            for sx in range(min(s.w, fb.width - win.x)):
                o = (sy * s.w + sx) * 4
                pix = ((s.pixels[o + 2] << 16) |
                       (s.pixels[o + 1] << 8)  |
                        s.pixels[o])
                fb.put_pixel(win.x + sx, fy, pix)

    def _redraw(self) -> None:
        fb = _fb_mod.fb
        if fb is None:
            return
        any_dirty = any(w.dirty for w in self._windows)
        if not any_dirty:
            return
        # Full-screen clear is cheap relative to per-window blit; keeps
        # things correct when windows move or close. v1 will track dirty
        # rects properly.
        fb.fill(self._desktop_bg)
        for win in self._windows:
            self._paint_chrome(win, fb)
            self._paint_window_body(win, fb)
            win.dirty = False

    # ── Event routing ───────────────────────────────────────────────────────

    def _route_event(self, ev) -> None:
        # Tab / Shift-Tab cycles focus globally
        if ev.kind == _gui_input.KEY_DOWN and ev.code == _gui_input.KEY_TAB:
            direction = -1 if (ev.mods & _gui_input.MOD_SHIFT) else 1
            self.cycle_focus(direction)
            return
        # Everything else goes to the focused window
        win = self.focused_window
        if win is not None:
            win.deliver(ev)

    # ── Tasks ───────────────────────────────────────────────────────────────

    async def _draw_loop(self) -> None:
        period = 1.0 / self._tick_hz
        while self._running:
            self._redraw()
            await asyncio.sleep(period)

    async def _input_loop(self) -> None:
        q = _gui_input.queue
        if q is None:
            _gui_input.init()
            q = _gui_input.queue
        while self._running:
            ev = await q.get()
            self._route_event(ev)
            # Reap closed windows lazily
            for w in list(self._windows):
                if w._closed:
                    self.remove_window(w)

    def start(self, loop=None) -> None:
        if self._running:
            return
        self._running = True
        loop = loop or asyncio.get_event_loop()
        self._tasks.append(loop.create_task(self._draw_loop()))
        self._tasks.append(loop.create_task(self._input_loop()))
        log.info("compositor: started")

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()


# Module-level singleton
compositor = Compositor()
