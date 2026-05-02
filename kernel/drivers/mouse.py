"""
kernel.drivers.mouse — PS/2 auxiliary-device (mouse) driver.

Reads 3-byte movement packets from port 0x60 on IRQ 12. Exposes a
synchronous subscribe(callback) hook so the GUI input bridge can
forward each packet as a normalized :class:`kernel.gui.input.Event`
without paying for an asyncio queue per IRQ.

Wire-up sequence (PS/2 controller on q35):

    1. CMD 0xA8   — enable auxiliary device
    2. CMD 0x20   — read controller config byte
       data IN   — config byte
       set bit 1 (enable IRQ12), clear bit 5 (clock not disabled)
    3. CMD 0x60   — write controller config byte
       data OUT  — modified config
    4. CMD 0xD4   — next byte targets the mouse
       data OUT  — 0xF6  (set defaults)
       data IN   — 0xFA  (ACK)
    5. CMD 0xD4
       data OUT  — 0xF4  (enable data reporting)
       data IN   — 0xFA  (ACK)

After step 5 every mouse movement / button click generates an IRQ12
with a 3-byte packet at port 0x60.
"""

from dataclasses import dataclass

from kernel.hal.io import inb, outb
from kernel.interrupts.router import interrupt, IRQ
import kernel.log as log


PS2_DATA   = 0x60
PS2_STATUS = 0x64
PS2_CMD    = 0x64

PIC_MASTER_MASK = 0x21
PIC_SLAVE_MASK  = 0xA1

CMD_ENABLE_AUX           = 0xA8
CMD_READ_CONFIG          = 0x20
CMD_WRITE_CONFIG         = 0x60
CMD_WRITE_TO_MOUSE       = 0xD4

MOUSE_CMD_SET_DEFAULTS   = 0xF6
MOUSE_CMD_ENABLE_REPORT  = 0xF4
MOUSE_REPLY_ACK          = 0xFA

STATUS_OUTPUT_FULL       = 0x01
STATUS_INPUT_FULL        = 0x02
STATUS_FROM_AUX          = 0x20

PKT_LBTN  = 0x01
PKT_RBTN  = 0x02
PKT_MBTN  = 0x04
PKT_X_SIGN = 0x10
PKT_Y_SIGN = 0x20


@dataclass(frozen=True, slots=True)
class MouseEvent:
    dx:      int   # signed; positive = right
    dy:      int   # signed; positive = down (Y already inverted)
    lbtn:    bool
    rbtn:    bool
    mbtn:    bool
    button_changed: int  # PKT_LBTN/RBTN/MBTN if a button just transitioned, else 0
    pressed: bool        # only meaningful if button_changed != 0


def _wait_writable(timeout: int = 100_000) -> bool:
    for _ in range(timeout):
        if not (inb(PS2_STATUS) & STATUS_INPUT_FULL):
            return True
    return False


def _wait_readable(timeout: int = 100_000) -> bool:
    for _ in range(timeout):
        if inb(PS2_STATUS) & STATUS_OUTPUT_FULL:
            return True
    return False


def _ctrl_send(cmd: int) -> None:
    if not _wait_writable():
        return
    outb(PS2_CMD, cmd)


def _data_send(value: int) -> None:
    if not _wait_writable():
        return
    outb(PS2_DATA, value)


def _data_recv(default: int = 0) -> int:
    if not _wait_readable():
        return default
    return inb(PS2_DATA)


def _mouse_send(value: int) -> int:
    """Send a byte to the mouse via the controller; returns ACK byte."""
    _ctrl_send(CMD_WRITE_TO_MOUSE)
    _data_send(value)
    return _data_recv()


def _unmask_irq12() -> None:
    # IRQ12 is on the slave PIC (bit 4 of the slave mask).  Also unmask
    # the cascade (IRQ2) on the master so slave interrupts propagate.
    outb(PIC_SLAVE_MASK,  inb(PIC_SLAVE_MASK)  & ~0x10)
    outb(PIC_MASTER_MASK, inb(PIC_MASTER_MASK) & ~0x04)


class MouseDriver:

    def __init__(self) -> None:
        self._initialized = False
        self._buf: list[int] = []
        self._lbtn = False
        self._rbtn = False
        self._mbtn = False
        self._subscribers: list = []

    def subscribe(self, callback) -> None:
        self._subscribers.append(callback)

    def init(self) -> bool:
        if self._initialized:
            return True

        # Drain anything already pending.
        for _ in range(16):
            if not (inb(PS2_STATUS) & STATUS_OUTPUT_FULL):
                break
            inb(PS2_DATA)

        _ctrl_send(CMD_ENABLE_AUX)

        _ctrl_send(CMD_READ_CONFIG)
        cfg = _data_recv(0)
        cfg |= (1 << 1)    # enable IRQ12
        cfg &= ~(1 << 5)   # mouse clock not disabled
        _ctrl_send(CMD_WRITE_CONFIG)
        _data_send(cfg)

        ack1 = _mouse_send(MOUSE_CMD_SET_DEFAULTS)
        ack2 = _mouse_send(MOUSE_CMD_ENABLE_REPORT)
        if ack1 != MOUSE_REPLY_ACK or ack2 != MOUSE_REPLY_ACK:
            log.info(f"mouse: ACK mismatch ({ack1:#x},{ack2:#x}); proceeding anyway")

        _unmask_irq12()
        self._initialized = True
        log.info("mouse: PS/2 ready (IRQ12)")
        return True

    # ── IRQ path ────────────────────────────────────────────────────────────

    def handle_irq(self) -> None:
        # Only consume the byte if status says it's from the aux device —
        # otherwise we'd accidentally swallow a keyboard scancode.
        st = inb(PS2_STATUS)
        if not (st & STATUS_OUTPUT_FULL) or not (st & STATUS_FROM_AUX):
            return
        b = inb(PS2_DATA)
        self._buf.append(b)
        if len(self._buf) < 3:
            return

        b0, b1, b2 = self._buf
        self._buf = []

        # Re-sync if byte0 has bit 3 == 0 (must always be 1).
        if not (b0 & 0x08):
            return

        dx = (b1 - 256) if (b0 & PKT_X_SIGN) else b1
        dy = (b2 - 256) if (b0 & PKT_Y_SIGN) else b2
        # PS/2 reports Y up = positive; flip to "screen y" (down = positive).
        dy = -dy

        new_l = bool(b0 & PKT_LBTN)
        new_r = bool(b0 & PKT_RBTN)
        new_m = bool(b0 & PKT_MBTN)

        # Movement event
        if dx != 0 or dy != 0:
            ev = MouseEvent(dx=dx, dy=dy, lbtn=new_l, rbtn=new_r, mbtn=new_m,
                             button_changed=0, pressed=False)
            for cb in self._subscribers:
                try:
                    cb(ev)
                except Exception:
                    pass

        # Button-transition events (one per changed button)
        for mask, was, now in (
            (PKT_LBTN, self._lbtn, new_l),
            (PKT_RBTN, self._rbtn, new_r),
            (PKT_MBTN, self._mbtn, new_m),
        ):
            if was != now:
                ev = MouseEvent(dx=0, dy=0, lbtn=new_l, rbtn=new_r, mbtn=new_m,
                                 button_changed=mask, pressed=now)
                for cb in self._subscribers:
                    try:
                        cb(ev)
                    except Exception:
                        pass

        self._lbtn, self._rbtn, self._mbtn = new_l, new_r, new_m


# Module-level singleton
mouse = MouseDriver()


@interrupt(IRQ.MOUSE)
def _mouse_irq(ctx) -> None:
    mouse.handle_irq()
