"""
kernel.sound.hda — Intel High Definition Audio (HDA / Azalia) driver.

HDA is the audio subsystem in virtually all modern PCs and QEMU's default
sound card (-device intel-hda -device hda-duplex).

Architecture:
  - A controller with one or more codec chips connected via a serial bus
  - The controller has a DMA engine with Buffer Descriptor Lists (BDLs)
  - Codecs expose "widgets": DACs, ADCs, mixers, pin complexes
  - We use the simplest path: find the first output DAC, configure it,
    and DMA PCM data to it.

Register space: MMIO, base address from PCI BAR0.
Spec: Intel HD Audio Specification 1.0a
"""


import asyncio
import struct
from dataclasses import dataclass
from typing import Protocol

from kernel.bus.pci import PCIDevice, PCIDriver, PCIClass
from kernel.hal.io  import mmio_read32, mmio_write32, mmio_write8
import kernel.log as log

# ── PCI identity ──────────────────────────────────────────────────────────────
HDA_VENDOR_INTEL  = 0x8086
HDA_DEVICE_ICH6   = 0x2668   # QEMU default
HDA_CLASS         = PCIClass.MULTIMEDIA

# ── MMIO register offsets ─────────────────────────────────────────────────────
GCAP    = 0x00   # Global Capabilities
GCTL    = 0x08   # Global Control
WAKEEN  = 0x0C   # Wake Enable
STATESTS= 0x0E   # State Change Status
INTCTL  = 0x20   # Interrupt Control
INTSTS  = 0x24   # Interrupt Status
WALCLK  = 0x30   # Wall Clock Counter
CORBLBASE= 0x40  # CORB Lower Base
CORBUBASE= 0x44  # CORB Upper Base
CORBWP  = 0x48   # CORB Write Pointer
CORBRP  = 0x4A   # CORB Read Pointer
CORBCTL = 0x4C   # CORB Control
CORBSTS = 0x4D   # CORB Status
CORBSIZE= 0x4E   # CORB Size
RIRLBASE= 0x50   # RIRB Lower Base
RIRUBASE= 0x54   # RIRB Upper Base
RIRBWP  = 0x58   # RIRB Write Pointer
RIRBCTL = 0x5C   # RIRB Control
RIRBSTS = 0x5D   # RIRB Status
RIRBSIZE= 0x5E   # RIRB Size
ICOI    = 0x60   # Immediate Command Output
ICII    = 0x64   # Immediate Command Input
ICIS    = 0x68   # Immediate Command Status

# Stream descriptor base (output stream 0 = 0x80 + 0*0x20)
SDBASE  = 0x80
SDSTRIDE= 0x20

# Stream descriptor offsets
SD_CTL  = 0x00
SD_STS  = 0x03
SD_LPIB = 0x04
SD_CBL  = 0x08
SD_LVI  = 0x0C
SD_FMT  = 0x12
SD_BDPL = 0x18
SD_BDPU = 0x1C

# ── HDA codec verb helpers ────────────────────────────────────────────────────

def make_verb(codec: int, nid: int, verb: int, payload: int) -> int:
    return (codec << 28) | (nid << 20) | (verb << 8) | (payload & 0xFF)

# Verbs
GET_PARAM      = 0xF00
SET_STREAM_FMT = 0x200
SET_ANALOG_CTL = 0x300   # EAPD
SET_PIN_WIDGET  = 0x707
SET_CONN_SEL    = 0xF01
SET_POWER_STATE = 0x705

# Parameters
PARAM_VENDOR    = 0x00
PARAM_NODE_COUNT= 0x04
PARAM_FUNC_TYPE = 0x05
PARAM_AUDIO_CAP = 0x09
PARAM_PIN_CAP   = 0x0C
PARAM_CONN_LIST_LEN = 0x0E

# ── Audio format word ─────────────────────────────────────────────────────────

def make_format(sample_rate: int = 44100,
                bits: int = 16,
                channels: int = 2) -> int:
    # HDA stream format: BASE|MULT|DIV|BITS|CHAN
    # 44100 = 48000 * 147/160 — approximate as 48000/1
    base = 0      # 48 kHz base
    mult = 0      # x1
    div  = 0      # /1  -> 48000 Hz
    bits_code = {8: 0, 16: 1, 20: 2, 24: 3, 32: 4}.get(bits, 1)
    return (base << 14) | (mult << 11) | (div << 8) | (bits_code << 4) | (channels - 1)

SAMPLE_RATE = 48000
CHANNELS    = 2
BIT_DEPTH   = 16
BUFFER_MS   = 20    # 20 ms DMA buffer
BUFFER_FRAMES = SAMPLE_RATE * BUFFER_MS // 1000   # 960 frames
BUFFER_BYTES  = BUFFER_FRAMES * CHANNELS * (BIT_DEPTH // 8)   # 3840 bytes
NUM_BDL_ENTRIES = 8   # number of BDL segments

@dataclass
class BDLEntry:
    """Buffer Descriptor List entry: 16 bytes."""
    addr:   int   # physical address of PCM buffer
    length: int
    ioc:    int   # interrupt-on-completion

    def pack(self) -> bytes:
        return struct.pack("<QII", self.addr, self.length, self.ioc)


class HDADriver:
    VENDOR  = HDA_VENDOR_INTEL
    DEVICE  = HDA_DEVICE_ICH6

    def __init__(self) -> None:
        self._base  = 0
        self._codec = 0
        self._dac_nid = 0
        self._out_bufs_phys: list[int] = []
        self._out_seg_bytes = 0
        self._write_idx = 0
        self._play_task: asyncio.Task | None = None

    def probe(self, dev: PCIDevice) -> bool:
        if not dev.bars:
            return False
        self._base = dev.bars[0] & ~0xF   # MMIO base (mask type bits)
        log.info(f"hda: MMIO base = {self._base:#010x}")

        # Reset controller
        self._r32(GCTL)  # read
        self._w32(GCTL, 0)                     # assert CRST
        for _ in range(1000): pass             # wait
        self._w32(GCTL, 1)                     # deassert CRST
        for _ in range(10000): pass            # wait for codecs

        # Check which codecs responded
        statests = self._r32(STATESTS)
        if not statests:
            log.warn("hda: no codecs found")
            return False

        self._codec = 0
        while not (statests & (1 << self._codec)):
            self._codec += 1

        log.info(f"hda: codec {self._codec} present")

        # Set up CORB/RIRB and find DAC output node
        self._setup_corb_rirb()
        self._enumerate_codec()
        self._setup_stream()

        log.info("hda: driver ready")
        return True

    def _r32(self, off: int) -> int: return mmio_read32(self._base + off)
    def _w32(self, off: int, v: int) -> None: mmio_write32(self._base + off, v)

    def _send_verb_immediate(self, verb: int) -> int:
        """Use Immediate Command Interface (no CORB/RIRB needed for init)."""
        self._w32(ICOI, verb)
        self._w32(ICIS, 1)          # set ICB (trigger)
        for _ in range(10000):
            if self._r32(ICIS) & 2: # IRV: response valid
                break
        return self._r32(ICII)

    def _get_param(self, nid: int, param: int) -> int:
        return self._send_verb_immediate(
            make_verb(self._codec, nid, GET_PARAM, param))

    def _setup_corb_rirb(self) -> None:
        # For simplicity, use the Immediate Command Interface throughout.
        # A production driver would use CORB/RIRB for throughput.
        pass

    def _enumerate_codec(self) -> None:
        # Root node has NID 0; get function group range
        fg_count = self._get_param(0, PARAM_NODE_COUNT)
        fg_start = (fg_count >> 16) & 0xFF
        fg_total = fg_count & 0xFF

        for fg_nid in range(fg_start, fg_start + fg_total):
            ftype = self._get_param(fg_nid, PARAM_FUNC_TYPE) & 0xFF
            if ftype != 1:   # 1 = audio function group
                continue
            # Enumerate widgets in this function group
            wid_info = self._get_param(fg_nid, PARAM_NODE_COUNT)
            w_start  = (wid_info >> 16) & 0xFF
            w_total  = wid_info & 0xFF
            for nid in range(w_start, w_start + w_total):
                cap = self._get_param(nid, PARAM_AUDIO_CAP)
                wtype = (cap >> 20) & 0xF
                if wtype == 0:  # Audio Output (DAC)
                    self._dac_nid = nid
                    log.info(f"hda: DAC at NID {nid}")
                    return

    def _setup_stream(self) -> None:
        if not self._dac_nid:
            return

        # Power up DAC
        self._send_verb_immediate(
            make_verb(self._codec, self._dac_nid, SET_POWER_STATE, 0))  # D0

        # Set stream format on DAC
        fmt = make_format(SAMPLE_RATE, BIT_DEPTH, CHANNELS)
        self._send_verb_immediate(
            make_verb(self._codec, self._dac_nid, SET_STREAM_FMT, fmt & 0xFF) |
            ((fmt >> 8) << 8))

        # Allocate DMA buffers via C heap (GC-safe, persistent)
        import _hal
        seg_bytes = BUFFER_BYTES // NUM_BDL_ENTRIES
        self._out_seg_bytes = seg_bytes
        self._out_bufs_phys = [_hal.dma_alloc(seg_bytes) for _ in range(NUM_BDL_ENTRIES)]

        # Build BDL in memory
        bdl_phys = _hal.dma_alloc(NUM_BDL_ENTRIES * 16)
        for i, buf_phys in enumerate(self._out_bufs_phys):
            entry = BDLEntry(addr=buf_phys, length=seg_bytes, ioc=1)
            packed = entry.pack()
            import struct as _s
            words = _s.unpack("<4I", packed)
            for j, w in enumerate(words):
                mmio_write32(bdl_phys + i * 16 + j * 4, w)

        # Program output stream descriptor (stream 0 = first output)
        sd_off = SDBASE   # first output stream

        # Stop stream, reset
        self._w32(sd_off + SD_CTL, 0)
        for _ in range(1000): pass
        self._w32(sd_off + SD_CTL, 1)  # SRST
        for _ in range(1000): pass
        self._w32(sd_off + SD_CTL, 0)

        # Set BDL address, cyclic buffer length, last valid index, format
        self._w32(sd_off + SD_BDPL, bdl_phys & 0xFFFFFFFF)
        self._w32(sd_off + SD_BDPU, bdl_phys >> 32)
        self._w32(sd_off + SD_CBL,  BUFFER_BYTES)
        self._w32(sd_off + SD_LVI,  NUM_BDL_ENTRIES - 1)
        self._w32(sd_off + SD_FMT,  fmt)

        # Assign to stream tag 1
        ctl = self._r32(sd_off + SD_CTL)
        ctl = (ctl & ~(0xF << 20)) | (1 << 20)   # stream tag = 1
        self._w32(sd_off + SD_CTL, ctl)

        # Run
        self._w32(sd_off + SD_CTL, ctl | 2)   # RUN bit

        log.info("hda: output stream running")

    # ── Public API ─────────────────────────────────────────────────────────────

    def write_pcm(self, pcm: bytes) -> int:
        """
        Write raw signed-16-bit stereo PCM samples.
        Returns number of bytes consumed.
        Non-blocking: drops data if buffer is full.
        """
        if not self._out_bufs_phys or self._out_seg_bytes <= 0:
            return 0

        total = 0
        slots = 0
        while total < len(pcm) and slots < NUM_BDL_ENTRIES:
            phys = self._out_bufs_phys[self._write_idx % NUM_BDL_ENTRIES]
            n = min(len(pcm) - total, self._out_seg_bytes)
            chunk = pcm[total:total + n]
            for i in range(0, len(chunk) - 3, 4):
                w = (chunk[i] |
                     (chunk[i + 1] << 8) |
                     (chunk[i + 2] << 16) |
                     (chunk[i + 3] << 24))
                mmio_write32(phys + i, w)
            for i in range(len(chunk) - (len(chunk) % 4), len(chunk)):
                mmio_write8(phys + i, chunk[i])
            total += n
            self._write_idx += 1
            slots += 1
        return total

    def generate_tone(self, freq: int = 440, ms: int = 1000) -> bytes:
        """Generate a sine wave tone as PCM bytes (for testing)."""
        import math
        frames = SAMPLE_RATE * ms // 1000
        out = bytearray(frames * CHANNELS * 2)
        amp = 16000
        for i in range(frames):
            sample = int(amp * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
            s16 = struct.pack("<h", max(-32768, min(32767, sample)))
            out[i * 4:i * 4 + 2] = s16   # left
            out[i * 4 + 2:i * 4 + 4] = s16  # right
        return bytes(out)


# Module-level singleton
hda: HDADriver | None = None
