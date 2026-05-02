"""
kernel.sound.mixer — Architecture-neutral PCM playback API.

Wraps the existing low-level audio drivers (HDA on x86, virtio-snd on
arm64 — follow-up) behind a single :class:`Mixer` so the sdl2.sdlmixer
shim and apps can target one surface. The native sample format is
signed 16-bit stereo at the rate the underlying device negotiated;
incoming samples in other formats are converted in pure Python.
"""

import struct
import kernel.log as log


# ── Format conversion helpers ───────────────────────────────────────────────

def _to_int16_stereo(samples: bytes, channels: int,
                     fmt: str) -> bytes:
    """Convert ``samples`` to native int16 stereo bytes.

    fmt: 'int16' or 'float32'.
    channels: 1 (mono → duplicated) or 2 (passthrough).
    Sample rate conversion is NOT done here — caller must already match
    the device rate.
    """
    if fmt == "int16" and channels == 2:
        return bytes(samples)

    if fmt == "int16" and channels == 1:
        # Duplicate each 2-byte sample
        out = bytearray(len(samples) * 2)
        for i in range(0, len(samples) - 1, 2):
            out[i * 2]     = samples[i]
            out[i * 2 + 1] = samples[i + 1]
            out[i * 2 + 2] = samples[i]
            out[i * 2 + 3] = samples[i + 1]
        return bytes(out)

    if fmt == "float32":
        n_floats = len(samples) // 4
        floats = struct.unpack(f"<{n_floats}f", samples)
        out = bytearray()
        if channels == 1:
            for f in floats:
                v = max(-1.0, min(1.0, f))
                s = int(v * 32767)
                w = struct.pack("<h", s)
                out += w + w   # mono → stereo
        else:
            for f in floats:
                v = max(-1.0, min(1.0, f))
                s = int(v * 32767)
                out += struct.pack("<h", s)
        return bytes(out)

    raise ValueError(f"unsupported audio format: {fmt!r}, channels={channels}")


# ── Mixer ───────────────────────────────────────────────────────────────────

class Mixer:
    """Single-channel PCM mixer over whichever audio backend is bound.

    The HDA backend hard-codes 48 kHz int16 stereo (see kernel.sound.hda
    constants); this matches the format Mixer normalizes to.
    """

    def __init__(self) -> None:
        self._backend = None
        self._rate    = 48000
        self._fmt     = "int16"
        self._channels = 2
        self._bytes_consumed = 0

    def attach(self, backend) -> None:
        """Bind the underlying device. Called from kernel.boot when the
        relevant driver successfully probed."""
        self._backend = backend
        log.info(f"mixer: attached backend {type(backend).__name__}")

    @property
    def native_rate(self) -> int: return self._rate
    @property
    def native_channels(self) -> int: return self._channels
    @property
    def bytes_consumed(self) -> int: return self._bytes_consumed

    def play_pcm(self, samples: bytes, channels: int = 2,
                 rate: int | None = None, fmt: str = "int16") -> int:
        """Push PCM samples to the backend. Returns bytes consumed.

        ``rate`` is informational for now — the backend runs at its own
        native rate. Caller is responsible for resampling.
        """
        if self._backend is None:
            return 0
        if rate not in (None, self._rate):
            log.info(f"mixer: ignoring rate={rate}; native is {self._rate}")
        normalized = _to_int16_stereo(samples, channels, fmt)
        n = self._backend.write_pcm(normalized)
        self._bytes_consumed += n
        return n

    def queue(self, samples: bytes, channels: int = 2,
              rate: int | None = None, fmt: str = "int16") -> int:
        """Alias of :meth:`play_pcm` — the HDA backend is itself a queue
        so there is no separate path to a play command."""
        return self.play_pcm(samples, channels, rate, fmt)

    def stop(self) -> None:
        """No-op for HDA — the stream stays running with silence
        between buffer refills. Wired for future backends that need
        an explicit stop."""
        pass


# Module-level singleton
mixer = Mixer()
