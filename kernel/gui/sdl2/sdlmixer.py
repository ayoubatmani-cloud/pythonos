"""sdl2.sdlmixer — Audio playback compat layer over kernel.sound.mixer.

Subset implemented for the corpus:
    Mix_OpenAudio, Mix_CloseAudio, Mix_LoadWAV, Mix_PlayChannel,
    Mix_HaltChannel, Mix_FreeChunk

Plays through the bound :class:`kernel.sound.mixer.Mixer`. WAV parsing
is in-place — only PCM int16 mono/stereo is supported, which is what
the corpus produces.
"""

import struct
import kernel.log as log
from kernel.sound.mixer import mixer


# PySDL2 / SDL_mixer constants
MIX_DEFAULT_FREQUENCY = 44100
MIX_DEFAULT_FORMAT    = 0x8010   # AUDIO_S16LSB
MIX_DEFAULT_CHANNELS  = 2
MIX_MAX_VOLUME        = 128


class Mix_Chunk:
    """A loaded sample; analogous to SDL_mixer's Mix_Chunk."""
    def __init__(self, samples: bytes, channels: int, fmt: str) -> None:
        self.samples  = samples
        self.channels = channels
        self.fmt      = fmt
        self.volume   = MIX_MAX_VOLUME

    @property
    def contents(self):
        return self


def Mix_OpenAudio(freq: int = MIX_DEFAULT_FREQUENCY,
                  fmt: int = MIX_DEFAULT_FORMAT,
                  channels: int = MIX_DEFAULT_CHANNELS,
                  chunksize: int = 1024) -> int:
    if mixer.native_rate != freq:
        log.info(f"Mix_OpenAudio: requested freq={freq}, using native "
                 f"{mixer.native_rate} (no resampling in v0)")
    return 0


def Mix_CloseAudio() -> None:
    mixer.stop()


def _parse_wav(data: bytes) -> tuple[bytes, int, str]:
    """Return (pcm_bytes, channels, fmt). Raises on unsupported format."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Mix_LoadWAV: not a WAV file")
    # Walk subchunks
    off = 12
    fmt_chan = 0
    fmt_bps = 0
    fmt_code = 0
    pcm = b""
    while off + 8 <= len(data):
        cid  = data[off:off+4]
        size = int.from_bytes(data[off+4:off+8], "little")
        body = data[off+8:off+8+size]
        if cid == b"fmt ":
            fmt_code = int.from_bytes(body[0:2], "little")
            fmt_chan = int.from_bytes(body[2:4], "little")
            fmt_bps  = int.from_bytes(body[14:16], "little")
        elif cid == b"data":
            pcm = body
        off += 8 + size + (size & 1)   # padding to even
    if fmt_code != 1 or fmt_bps != 16 or fmt_chan not in (1, 2):
        raise ValueError(
            f"Mix_LoadWAV: unsupported (fmt={fmt_code}, bps={fmt_bps}, "
            f"chan={fmt_chan}); v0 only handles PCM int16 mono/stereo")
    return pcm, fmt_chan, "int16"


def Mix_LoadWAV(path):
    p = path.decode() if isinstance(path, (bytes, bytearray)) else str(path)
    with open(p, "rb") as f:
        data = f.read()
    pcm, ch, fmt = _parse_wav(data)
    return Mix_Chunk(pcm, ch, fmt)


def Mix_PlayChannel(channel: int, chunk, loops: int = 0) -> int:
    """Play ``chunk`` once. ``channel`` and ``loops`` are accepted but
    not honoured in v0 — there is one stream and no loop scheduling."""
    c = chunk.contents if hasattr(chunk, "contents") else chunk
    mixer.play_pcm(c.samples, channels=c.channels, fmt=c.fmt)
    return channel if channel >= 0 else 0


def Mix_HaltChannel(channel: int) -> int:
    mixer.stop()
    return 0


def Mix_FreeChunk(chunk) -> None:
    pass  # GC handles it
