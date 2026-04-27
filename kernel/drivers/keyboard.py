"""
kernel.drivers.keyboard — PS/2 keyboard driver.

Reads scancodes from port 0x60 on IRQ 1.
Translates Set-1 scancodes to key names and characters.
Provides an async queue for consumers (shell, apps).
"""


import asyncio
from dataclasses import dataclass
from enum import IntEnum

from kernel.hal.io import inb
from kernel.interrupts.router import interrupt, IRQ


# ── Scancode set 1 (XT / AT make codes) ──────────────────────────────────────

_SCANCODE_MAP: dict[int, tuple[str, str]] = {
    # scan: (unshifted, shifted)
    0x01: ('esc',   'esc'),
    0x02: ('1',     '!'),   0x03: ('2',  '@'),  0x04: ('3', '#'),
    0x05: ('4',     '$'),   0x06: ('5',  '%'),  0x07: ('6', '^'),
    0x08: ('7',     '&'),   0x09: ('8',  '*'),  0x0A: ('9', '('),
    0x0B: ('0',     ')'),   0x0C: ('-',  '_'),  0x0D: ('=', '+'),
    0x0E: ('backspace', 'backspace'),
    0x0F: ('tab',   'tab'),
    0x10: ('q','Q'), 0x11: ('w','W'), 0x12: ('e','E'), 0x13: ('r','R'),
    0x14: ('t','T'), 0x15: ('y','Y'), 0x16: ('u','U'), 0x17: ('i','I'),
    0x18: ('o','O'), 0x19: ('p','P'), 0x1A: ('[','{'), 0x1B: (']','}'),
    0x1C: ('\n','\n'),   # enter
    0x1D: ('lctrl', 'lctrl'),
    0x1E: ('a','A'), 0x1F: ('s','S'), 0x20: ('d','D'), 0x21: ('f','F'),
    0x22: ('g','G'), 0x23: ('h','H'), 0x24: ('j','J'), 0x25: ('k','K'),
    0x26: ('l','L'), 0x27: (';',':'), 0x28: ("'",'"'), 0x29: ('`','~'),
    0x2A: ('lshift','lshift'),
    0x2B: ('\\','|'),
    0x2C: ('z','Z'), 0x2D: ('x','X'), 0x2E: ('c','C'), 0x2F: ('v','V'),
    0x30: ('b','B'), 0x31: ('n','N'), 0x32: ('m','M'), 0x33: (',','<'),
    0x34: ('.','>'), 0x35: ('/','?'),
    0x36: ('rshift','rshift'),
    0x37: ('*','*'),     # keypad *
    0x38: ('lalt','lalt'),
    0x39: (' ',' '),     # space
    0x3A: ('capslock','capslock'),
    0x48: ('up',   'up'),
    0x50: ('down', 'down'),
    0x4B: ('left', 'left'),
    0x4D: ('right','right'),
    0x53: ('delete','delete'),
}


@dataclass(frozen=True, slots=True)
class KeyEvent:
    scancode: int
    key:      str    # canonical key name
    char:     str    # printable character ('' for special keys)
    pressed:  bool
    shift:    bool
    ctrl:     bool
    alt:      bool


class KeyboardDriver:
    PS2_DATA = 0x60
    PS2_STATUS = 0x64

    def __init__(self) -> None:
        self._queue:    asyncio.Queue[KeyEvent] = asyncio.Queue(maxsize=256)
        self._shift     = False
        self._ctrl      = False
        self._alt       = False
        self._capslock  = False

    def _unmask_irq1(self) -> None:
        from kernel.hal.io import inb, outb
        mask = inb(0x21)
        outb(0x21, mask & ~0x02)   # clear bit 1 (IRQ 1)

    def init(self) -> None:
        self._unmask_irq1()

    def handle_irq(self) -> None:
        """Called synchronously from interrupt handler — must be fast."""
        sc = inb(self.PS2_DATA)
        released  = bool(sc & 0x80)
        make_code = sc & 0x7F

        entry = _SCANCODE_MAP.get(make_code)
        if entry is None:
            return

        key_unshifted, key_shifted = entry
        key = key_unshifted  # base name

        # Track modifier state
        if key in ('lshift', 'rshift'):
            self._shift = not released
            return
        if key == 'lctrl':
            self._ctrl = not released
            return
        if key == 'lalt':
            self._alt = not released
            return
        if key == 'capslock' and not released:
            self._capslock = not self._capslock
            return

        shifted = self._shift ^ self._capslock
        char_str = (key_shifted if shifted else key_unshifted)
        # Only single characters are printable; named keys are empty
        char = char_str if len(char_str) == 1 else ''

        event = KeyEvent(
            scancode=make_code,
            key=key_unshifted,
            char=char,
            pressed=not released,
            shift=self._shift,
            ctrl=self._ctrl,
            alt=self._alt,
        )

        if not released:
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                pass   # drop on overflow — keyboard buffer full

    async def read(self) -> KeyEvent:
        """Async read — suspends until a key is pressed."""
        return await self._queue.get()

    async def read_char(self) -> str:
        """Read next printable character, skipping non-printable keys."""
        while True:
            ev = await self.read()
            if ev.char:
                return ev.char


# Module-level singleton
keyboard = KeyboardDriver()

# Wire interrupt handler — imported by kernel.interrupts.handlers but
# also importable standalone so the driver self-registers.
@interrupt(IRQ.KEYBOARD)
def _keyboard_irq(ctx) -> None:
    keyboard.handle_irq()
