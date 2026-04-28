"""A small modal line editor for TmpFS files."""

from kernel.fs.vfs import vfs, OpenFlags


def _line(write, text=""):
    if write:
        write(text + "\n")
    else:
        print(text)


def _abspath(path, cwd):
    if path.startswith("/"):
        return path
    return cwd.rstrip("/") + "/" + path


async def _load(path):
    try:
        fd = await vfs.open(path)
    except Exception:
        return [""]
    data = b""
    while True:
        chunk = await vfs.read(fd, 4096)
        if not chunk:
            break
        data = data + chunk
    vfs.close(fd)
    text = data.decode("utf-8", errors="replace")
    return text.split("\n") if text else [""]


async def _save(path, lines):
    fd = await vfs.open(path, OpenFlags.WRONLY | OpenFlags.CREAT | OpenFlags.TRUNC)
    await vfs.write(fd, ("\n".join(lines)).encode("utf-8"))
    vfs.close(fd)


def _render(write, path, lines, cursor, dirty):
    _line(write)
    _line(write, "mini_vi  " + path + ("  [+]" if dirty else ""))
    _line(write, "commands: i insert  a append  x delete  j/k move  w write  q quit")
    start = cursor - 4
    if start < 0:
        start = 0
    stop = min(len(lines), start + 9)
    for idx in range(start, stop):
        mark = ">" if idx == cursor else " "
        _line(write, mark + str(idx + 1).rjust(3) + "  " + lines[idx])


async def _read_insert(read_char, write):
    _line(write, "-- INSERT -- finish with Enter, cancel with Esc")
    buf = ""
    while True:
        ch = await read_char()
        if ch == "\x1b":
            _line(write)
            return None
        if ch == "\n":
            _line(write)
            return buf
        if ch == "\b" or ord(ch) == 127:
            if buf:
                buf = buf[:-1]
                write("\b \b")
            continue
        buf += ch
        write(ch)


async def main(argv=None, cwd="/", read_char=None, write=None):
    argv = argv or []
    if read_char is None or write is None:
        _line(write, "mini_vi needs an interactive shell.")
        return

    path = _abspath(argv[0], cwd) if argv else "/tmp/notes.txt"
    lines = await _load(path)
    cursor = 0
    dirty = False

    while True:
        _render(write, path, lines, cursor, dirty)
        ch = await read_char()
        if ch == "q":
            if dirty:
                _line(write, "unsaved changes; press q again to quit")
                ch2 = await read_char()
                if ch2 != "q":
                    continue
            break
        if ch == "w":
            await _save(path, lines)
            dirty = False
            _line(write, "wrote " + path)
        elif ch == "j":
            cursor = min(cursor + 1, len(lines) - 1)
        elif ch == "k":
            cursor = max(cursor - 1, 0)
        elif ch == "x":
            if lines:
                del lines[cursor]
                if not lines:
                    lines.append("")
                cursor = min(cursor, len(lines) - 1)
                dirty = True
        elif ch == "i" or ch == "a":
            line = await _read_insert(read_char, write)
            if line is not None:
                pos = cursor if ch == "i" else cursor + 1
                lines.insert(pos, line)
                cursor = pos
                dirty = True
        elif ch == "?":
            _line(write, "mini_vi uses single-key commands; no terminal control codes required.")

    _line(write, "closed " + path)

