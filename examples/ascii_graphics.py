"""Animated ASCII graphics demo for PythonOS."""

import asyncio


def _line(write, text=""):
    if write:
        write(text + "\n")
    else:
        print(text)


async def main(argv=None, cwd="/", read_char=None, write=None):
    argv = argv or []
    frames = int(argv[0]) if argv else 10
    width = 54
    height = 13
    logo = "PYTHONOS"

    _line(write, "ASCII graphics demo")
    _line(write, "Rendering " + str(frames) + " frames from a frozen Python module.")

    for frame in range(frames):
        _line(write)
        _line(write, "frame " + str(frame + 1).rjust(2) + "/" + str(frames))
        for y in range(height):
            row = []
            for x in range(width):
                border = y == 0 or y == height - 1 or x == 0 or x == width - 1
                wave = (x * x + y * 7 + frame * 5) % 29 == 0
                stripe = (x + frame) % 17 == 0 and 2 < y < height - 3
                if border:
                    row.append("#")
                elif y == height // 2 and 20 <= x < 20 + len(logo):
                    row.append(logo[x - 20])
                elif wave:
                    row.append("*")
                elif stripe:
                    row.append("|")
                else:
                    row.append(" ")
            _line(write, "".join(row))
        await asyncio.sleep(0.07)

    _line(write, "done")

