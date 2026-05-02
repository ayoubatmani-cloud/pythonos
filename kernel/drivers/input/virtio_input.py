"""
kernel.drivers.input.virtio_input — VirtIO-Input over MMIO (arm64).

QEMU's ``-device virtio-keyboard-device``, ``virtio-mouse-device``, and
``virtio-tablet-device`` all expose virtio-input (DeviceID=18). v0 of
this driver covers keyboard events only — translating the standard
Linux ``EV_KEY`` codes into our portable ``KEY_*`` set and posting them
to :data:`kernel.gui.input.queue`. Mouse/tablet (EV_REL/EV_ABS) lands
with the arm64 mouse follow-up.

Transport: shared virtio-mmio scaffolding (the same descriptor /
avail / used ring layout used by ``virtio_blk``). Each event is the
8-byte struct::

    uint16 type;    // 1=EV_KEY, 2=EV_REL, 3=EV_ABS, 0=EV_SYN
    uint16 code;
    uint32 value;   // 1=press, 0=release, 2=repeat for EV_KEY

We pre-fill the event virtqueue with ``QUEUE_SIZE`` write-back
descriptors and re-queue each one after consuming the device's reply.
A single asyncio task at 50 Hz drains the used ring; that's plenty for
human input and avoids the IRQ-routing wiring on arm64 GICv2.
"""

import asyncio
import _hal
import kernel.log as log
from kernel.gui import input as _gui_input

VIRTIO_MMIO_BASE   = 0x0a000000
VIRTIO_MMIO_STRIDE = 0x200
VIRTIO_MMIO_DEVS   = 32
VIRTIO_MAGIC       = 0x74726976   # 'virt' LE
VIRTIO_DEV_INPUT   = 18

# Status bits
STATUS_ACK         = 1
STATUS_DRIVER      = 2
STATUS_FEATURES    = 8
STATUS_DRIVER_OK   = 4

# Descriptor flags
VRING_DESC_F_NEXT  = 1
VRING_DESC_F_WRITE = 2

PAGE_SIZE   = 4096
QUEUE_SIZE  = 32          # power of two, plenty of slack
EVENT_SIZE  = 8           # virtio_input_event

# Linux EV_* type values
EV_SYN = 0
EV_KEY = 1
EV_REL = 2
EV_ABS = 3


def _r32(base, off): return _hal.mmio_read32(base + off)
def _w32(base, off, v): _hal.mmio_write32(base + off, v)
def _w8 (addr, v): _hal.mmio_write8(addr, v)


# ── Linux EV_KEY → KEY_* mapping ────────────────────────────────────────────
# Subset covering printable ASCII, common modifiers, and arrows. Anything
# outside this table is silently dropped (with a debug log on first sight).

_EV_TO_KEY: dict[int, int] = {
    1:  _gui_input.KEY_ESC,
    14: _gui_input.KEY_BACKSPACE,
    15: _gui_input.KEY_TAB,
    28: _gui_input.KEY_ENTER,
    29: _gui_input.KEY_LCTRL,
    42: _gui_input.KEY_LSHIFT,
    54: _gui_input.KEY_RSHIFT,
    56: _gui_input.KEY_LALT,
    57: _gui_input.KEY_SPACE,
    58: _gui_input.KEY_CAPS_LOCK,
    97: _gui_input.KEY_RCTRL,
    100:_gui_input.KEY_RALT,
    103:_gui_input.KEY_UP,
    105:_gui_input.KEY_LEFT,
    106:_gui_input.KEY_RIGHT,
    108:_gui_input.KEY_DOWN,
    102:_gui_input.KEY_HOME,
    107:_gui_input.KEY_END,
    104:_gui_input.KEY_PAGE_UP,
    109:_gui_input.KEY_PAGE_DOWN,
    110:_gui_input.KEY_INSERT,
    111:_gui_input.KEY_DELETE,
    59: _gui_input.KEY_F1,  60: _gui_input.KEY_F2,
    61: _gui_input.KEY_F3,  62: _gui_input.KEY_F4,
    63: _gui_input.KEY_F5,  64: _gui_input.KEY_F6,
    65: _gui_input.KEY_F7,  66: _gui_input.KEY_F8,
    67: _gui_input.KEY_F9,  68: _gui_input.KEY_F10,
    87: _gui_input.KEY_F11, 88: _gui_input.KEY_F12,
}

# (unshifted, shifted) characters for printable EV_KEY codes.
_EV_TO_CHARS: dict[int, tuple[str, str]] = {
    2:  ("1","!"), 3: ("2","@"), 4: ("3","#"), 5: ("4","$"),
    6:  ("5","%"), 7: ("6","^"), 8: ("7","&"), 9: ("8","*"),
    10: ("9","("), 11:("0",")"), 12:("-","_"), 13:("=","+"),
    16: ("q","Q"), 17:("w","W"), 18:("e","E"), 19:("r","R"),
    20: ("t","T"), 21:("y","Y"), 22:("u","U"), 23:("i","I"),
    24: ("o","O"), 25:("p","P"), 26:("[","{"), 27:("]","}"),
    30: ("a","A"), 31:("s","S"), 32:("d","D"), 33:("f","F"),
    34: ("g","G"), 35:("h","H"), 36:("j","J"), 37:("k","K"),
    38: ("l","L"), 39:(";",":"), 40:("'",'"'),
    41: ("`","~"), 43:("\\","|"),
    44: ("z","Z"), 45:("x","X"), 46:("c","C"), 47:("v","V"),
    48: ("b","B"), 49:("n","N"), 50:("m","M"),
    51: (",","<"), 52:(".",">"), 53:("/","?"),
    57: (" "," "),
}

# Modifier-tracker EV codes
_EV_LSHIFT = 42
_EV_RSHIFT = 54
_EV_LCTRL  = 29
_EV_RCTRL  = 97
_EV_LALT   = 56
_EV_RALT   = 100


class VirtioMmioInput:
    """Single virtio-input keyboard device."""

    def __init__(self, base: int) -> None:
        self._base = base
        self._version = 0
        self._desc_phys  = 0
        self._avail_phys = 0
        self._used_phys  = 0
        self._buf_phys   = 0   # contiguous storage for QUEUE_SIZE 8-byte events
        self._next_desc  = 0
        self._avail_idx  = 0
        self._last_used  = 0
        self._shift = False
        self._ctrl  = False
        self._alt   = False

    # ── Probe ───────────────────────────────────────────────────────────

    def probe(self) -> bool:
        if _r32(self._base, 0x000) != VIRTIO_MAGIC:
            return False
        version = _r32(self._base, 0x004)
        if version not in (1, 2):
            return False
        if _r32(self._base, 0x008) != VIRTIO_DEV_INPUT:
            return False
        self._version = version

        _w32(self._base, 0x070, 0)
        _w32(self._base, 0x070, STATUS_ACK)
        _w32(self._base, 0x070, STATUS_ACK | STATUS_DRIVER)

        if version == 1:
            _w32(self._base, 0x028, PAGE_SIZE)
            _w32(self._base, 0x020, 0)
        else:
            _w32(self._base, 0x024, 0); _w32(self._base, 0x020, 0)
            _w32(self._base, 0x024, 1); _w32(self._base, 0x020, 0)

        _w32(self._base, 0x070, STATUS_ACK | STATUS_DRIVER | STATUS_FEATURES)

        # Set up event queue (queue 0).
        _w32(self._base, 0x030, 0)
        _w32(self._base, 0x038, QUEUE_SIZE)

        desc_sz   = QUEUE_SIZE * 16
        avail_sz  = 4 + QUEUE_SIZE * 2 + 2
        avail_off = desc_sz
        used_off  = (avail_off + avail_sz + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)
        used_sz   = 4 + QUEUE_SIZE * 8 + 2
        total     = used_off + used_sz

        raw = _hal.dma_alloc(total + PAGE_SIZE)
        base_phys = (raw + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)
        self._desc_phys  = base_phys
        self._avail_phys = base_phys + avail_off
        self._used_phys  = base_phys + used_off

        if self._version == 1:
            _w32(self._base, 0x03C, PAGE_SIZE)
            _w32(self._base, 0x040, base_phys >> 12)
        else:
            _w32(self._base, 0x080, base_phys             & 0xFFFFFFFF)
            _w32(self._base, 0x084, (base_phys >> 32)     & 0xFFFFFFFF)
            _w32(self._base, 0x090, self._avail_phys      & 0xFFFFFFFF)
            _w32(self._base, 0x094, (self._avail_phys >> 32) & 0xFFFFFFFF)
            _w32(self._base, 0x0A0, self._used_phys       & 0xFFFFFFFF)
            _w32(self._base, 0x0A4, (self._used_phys >> 32) & 0xFFFFFFFF)
            _w32(self._base, 0x044, 1)

        # One contiguous buffer holding QUEUE_SIZE 8-byte event slots.
        self._buf_phys = _hal.dma_alloc(QUEUE_SIZE * EVENT_SIZE)

        # Pre-fill every descriptor as a write-back into its dedicated slot.
        for i in range(QUEUE_SIZE):
            self._write_desc(i,
                              self._buf_phys + i * EVENT_SIZE,
                              EVENT_SIZE,
                              VRING_DESC_F_WRITE,
                              0)
            self._avail_push(i)

        _w32(self._base, 0x070,
             STATUS_ACK | STATUS_DRIVER | STATUS_FEATURES | STATUS_DRIVER_OK)

        # Kick the device so it starts filling slots.
        _w32(self._base, 0x050, 0)

        log.info(f"virtio-input: ready at {self._base:#x}")
        return True

    # ── Descriptor / ring helpers ───────────────────────────────────────

    def _write_desc(self, idx, addr, length, flags, nxt):
        base = self._desc_phys + idx * 16
        _hal.mmio_write32(base + 0,  addr & 0xFFFFFFFF)
        _hal.mmio_write32(base + 4,  (addr >> 32) & 0xFFFFFFFF)
        _hal.mmio_write32(base + 8,  length)
        _hal.mmio_write32(base + 12, (flags & 0xFFFF) | ((nxt & 0xFFFF) << 16))

    def _avail_push(self, head):
        slot = self._avail_idx % QUEUE_SIZE
        ring_addr = self._avail_phys + 4 + slot * 2
        _w8(ring_addr,     head & 0xFF)
        _w8(ring_addr + 1, (head >> 8) & 0xFF)
        self._avail_idx = (self._avail_idx + 1) & 0xFFFF
        idx_addr = self._avail_phys + 2
        _w8(idx_addr,     self._avail_idx & 0xFF)
        _w8(idx_addr + 1, (self._avail_idx >> 8) & 0xFF)

    def _used_idx(self):
        return _hal.mmio_read32(self._used_phys + 0) >> 16

    def _used_pop(self):
        slot = self._last_used % QUEUE_SIZE
        ring = self._used_phys + 4 + slot * 8
        desc_id = _hal.mmio_read32(ring) & 0xFFFFFFFF
        # length = _hal.mmio_read32(ring + 4) — always 8 here
        self._last_used = (self._last_used + 1) & 0xFFFF
        return desc_id

    # ── Event decode ────────────────────────────────────────────────────

    def _decode_one(self, desc_id):
        addr = self._buf_phys + desc_id * EVENT_SIZE
        b0 = _hal.mmio_read8(addr + 0); b1 = _hal.mmio_read8(addr + 1)
        b2 = _hal.mmio_read8(addr + 2); b3 = _hal.mmio_read8(addr + 3)
        b4 = _hal.mmio_read8(addr + 4); b5 = _hal.mmio_read8(addr + 5)
        b6 = _hal.mmio_read8(addr + 6); b7 = _hal.mmio_read8(addr + 7)
        type_  = b0 | (b1 << 8)
        code   = b2 | (b3 << 8)
        value  = b4 | (b5 << 8) | (b6 << 16) | (b7 << 24)
        return type_, code, value

    def _emit(self, type_, code, value):
        if type_ != EV_KEY:
            return
        # Track modifiers
        is_press = (value != 0)
        if code in (_EV_LSHIFT, _EV_RSHIFT):
            self._shift = is_press
            self._post_modifier(code, is_press)
            return
        if code in (_EV_LCTRL, _EV_RCTRL):
            self._ctrl = is_press
            self._post_modifier(code, is_press)
            return
        if code in (_EV_LALT, _EV_RALT):
            self._alt = is_press
            self._post_modifier(code, is_press)
            return

        if code in _EV_TO_CHARS:
            unshifted, shifted = _EV_TO_CHARS[code]
            ch = shifted if self._shift else unshifted
            keycode = ord(ch)
        elif code in _EV_TO_KEY:
            keycode = _EV_TO_KEY[code]
            ch = ""
        else:
            return    # unmapped — drop

        mods = 0
        if self._shift: mods |= _gui_input.MOD_SHIFT
        if self._ctrl:  mods |= _gui_input.MOD_CTRL
        if self._alt:   mods |= _gui_input.MOD_ALT

        kind = _gui_input.KEY_DOWN if is_press else _gui_input.KEY_UP
        ev = _gui_input.Event(kind=kind, code=keycode, text=ch, mods=mods)
        if _gui_input.queue != None:
            _gui_input.queue.post(ev)

    def _post_modifier(self, code, is_press):
        keycode = _EV_TO_KEY.get(code, _gui_input.KEY_NONE)
        if keycode == _gui_input.KEY_NONE:
            return
        kind = _gui_input.KEY_DOWN if is_press else _gui_input.KEY_UP
        mods = 0
        if self._shift: mods |= _gui_input.MOD_SHIFT
        if self._ctrl:  mods |= _gui_input.MOD_CTRL
        if self._alt:   mods |= _gui_input.MOD_ALT
        if _gui_input.queue != None:
            _gui_input.queue.post(_gui_input.Event(kind=kind, code=keycode,
                                                    text="", mods=mods))

    # ── Polling loop ────────────────────────────────────────────────────

    async def run(self) -> None:
        """Drain the used ring at ~50 Hz, post events, re-queue descriptors."""
        while True:
            target = self._used_idx() & 0xFFFF
            while (self._last_used & 0xFFFF) != target:
                desc_id = self._used_pop()
                t, c, v = self._decode_one(desc_id)
                self._emit(t, c, v)
                # Re-queue this descriptor
                self._avail_push(desc_id)
            # Kick the device after replenishment.
            _w32(self._base, 0x050, 0)
            await asyncio.sleep(0.02)


# ── Public discovery + setup ─────────────────────────────────────────────

def find_virtio_input() -> "VirtioMmioInput | None":
    for i in range(VIRTIO_MMIO_DEVS):
        base = VIRTIO_MMIO_BASE + i * VIRTIO_MMIO_STRIDE
        dev = VirtioMmioInput(base)
        if dev.probe():
            return dev
    return None


def install_virtio_input_bridge(scheduler) -> bool:
    """Bind the first virtio-input device, if present, and spawn its
    polling task on ``scheduler``. Returns True on success."""
    dev = find_virtio_input()
    if dev == None:
        return False
    _gui_input.init()
    scheduler.spawn(dev.run(), name="virtio-input-poller")
    return True
