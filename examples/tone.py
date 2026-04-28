"""Play a short melody through the HDA audio driver when available."""

import asyncio
import kernel.sound.hda as hda_mod


MELODY = [
    (330, 120), (392, 120), (494, 120), (660, 180),
    (494, 120), (392, 120), (330, 220),
]


def _line(write, text=""):
    if write:
        write(text + "\n")
    else:
        print(text)


async def _play_pcm(hda, pcm):
    offset = 0
    while offset < len(pcm):
        written = hda.write_pcm(pcm[offset:])
        if written <= 0:
            await asyncio.sleep(0.02)
        else:
            offset += written
            await asyncio.sleep(0.018)


async def main(argv=None, cwd="/", read_char=None, write=None):
    hda = hda_mod.hda
    if hda is None:
        _line(write, "No HDA device is available on this machine.")
        return

    _line(write, "Playing PythonOS melody through Intel HDA.")
    for freq, ms in MELODY:
        await _play_pcm(hda, hda.generate_tone(freq, ms))
    _line(write, "done")

