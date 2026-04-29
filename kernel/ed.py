"""
kernel.ed — a small ed(1)-style line editor for PythonOS.

This is a PythonOS port inspired by linarphy/py_ed. It keeps ed's useful
line-buffer model while replacing host operations with PythonOS VFS and shell
callbacks. Shell escapes and subprocess-backed reads/writes are intentionally
omitted because PythonOS has no userspace process model.
"""

from kernel.fs.vfs import vfs, OpenFlags


class EdError(Exception):
    pass


def _abspath(path, cwd):
    if path.startswith("/"):
        target = path
    else:
        target = cwd.rstrip("/") + "/" + path

    parts = []
    for seg in target.split("/"):
        if seg == "..":
            if parts:
                parts.pop()
        elif seg and seg != ".":
            parts.append(seg)
    return "/" + "/".join(parts)


async def _read_all(path):
    fd = await vfs.open(path)
    chunks = []
    try:
        while True:
            chunk = await vfs.read(fd, 4096)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        vfs.close(fd)
    return b"".join(chunks)


async def _write_all(path, data, append=False):
    flags = OpenFlags.WRONLY | OpenFlags.CREAT
    if append:
        flags |= OpenFlags.APPEND
    else:
        flags |= OpenFlags.TRUNC
    fd = await vfs.open(path, flags)
    try:
        await vfs.write(fd, data)
    finally:
        vfs.close(fd)


def _lines_from_text(text):
    if text == "":
        return []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _text_from_lines(lines):
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


class Editor:
    VERSION = "PythonOS ed 0.1"

    def __init__(self, argv, cwd, write, read_char):
        self.argv = argv or []
        self.cwd = cwd
        self.write = write
        self.read_char = read_char

        self.prompting = False
        self.prompt = "*"
        self.silent = False
        self.verbose = False

        self.file = ""
        self.lines = []
        self.saved_lines = []
        self.undo_lines = []
        self.dot = 0
        self.marks = {}
        self.cut = []
        self.running = True
        self.last_error = ""

    def out(self, text=""):
        self.write(text + "\n")

    def error(self, message):
        self.last_error = message
        if self.verbose:
            self.out(message)
        elif not self.silent:
            self.out("?")

    def changed(self):
        return self.lines != self.saved_lines

    def snapshot(self):
        self.undo_lines = self.lines[:]

    def set_dot(self, value):
        if not self.lines:
            self.dot = 0
        else:
            self.dot = max(1, min(len(self.lines), value))

    async def read_line(self, prompt=""):
        if prompt:
            self.write(prompt)
        buf = ""
        while True:
            ch = await self.read_char()
            if ch == "\n":
                self.write("\n")
                return buf
            if ch == "\b" or ch == "\x7f":
                if buf:
                    buf = buf[:-1]
                    self.write("\b \b")
                continue
            buf += ch
            self.write(ch)

    async def read_text(self):
        out = []
        while True:
            line = await self.read_line()
            if line == ".":
                return out
            out.append(line)

    async def load_file(self, path, force=False):
        path = _abspath(path, self.cwd)
        if self.changed() and not force:
            raise EdError("unsaved changes")
        try:
            data = await _read_all(path)
        except FileNotFoundError:
            self.file = path
            self.lines = []
            self.saved_lines = []
            self.undo_lines = []
            self.dot = 0
            return
        self.file = path
        self.lines = _lines_from_text(data.decode("utf-8", errors="replace"))
        self.saved_lines = self.lines[:]
        self.undo_lines = self.lines[:]
        self.dot = len(self.lines)
        if not self.silent:
            self.out(str(len(data)))

    async def write_file(self, path, start, end, append=False):
        if not path:
            path = self.file
        if not path:
            raise EdError("no current filename")
        path = _abspath(path, self.cwd)
        data = _text_from_lines(self.lines[start - 1:end] if start > 0 else [])
        await _write_all(path, data, append=append)
        if not append and start == 1 and end == len(self.lines):
            self.file = path
            self.saved_lines = self.lines[:]
        if not self.silent:
            self.out(str(len(data)))

    def parse_number(self, command, pos):
        start = pos
        while pos < len(command) and command[pos].isdigit():
            pos += 1
        return int(command[start:pos]), pos

    def parse_address(self, command, pos):
        n = len(command)
        while pos < n and command[pos] == " ":
            pos += 1
        if pos >= n:
            return None, pos

        ch = command[pos]
        if ch == ".":
            value = self.dot
            pos += 1
        elif ch == "$":
            value = len(self.lines)
            pos += 1
        elif ch == "'":
            if pos + 1 >= n:
                raise EdError("missing mark key")
            key = command[pos + 1]
            if key not in self.marks:
                raise EdError("mark not set")
            value = self.marks[key]
            pos += 2
        elif ch.isdigit():
            value, pos = self.parse_number(command, pos)
        elif ch in "+-":
            value = self.dot
        else:
            return None, pos

        while True:
            while pos < n and command[pos] == " ":
                pos += 1
            if pos >= n or command[pos] not in "+-":
                break
            sign = 1 if command[pos] == "+" else -1
            pos += 1
            while pos < n and command[pos] == " ":
                pos += 1
            if pos < n and command[pos].isdigit():
                offset, pos = self.parse_number(command, pos)
            else:
                offset = 1
            value += sign * offset

        return value, pos

    def parse_range(self, command):
        pos = 0
        n = len(command)
        addressed = False

        while pos < n and command[pos] == " ":
            pos += 1

        if pos < n and command[pos] == ",":
            start, end = self.whole_range()
            return start, end, pos + 1, True
        if pos < n and command[pos] == ";":
            start = self.dot
            end = len(self.lines)
            return start, end, pos + 1, True

        first, pos2 = self.parse_address(command, pos)
        if first is None:
            return None, None, pos, False
        addressed = True
        pos = pos2

        while pos < n and command[pos] == " ":
            pos += 1
        if pos < n and command[pos] in ",;":
            sep = command[pos]
            pos += 1
            if sep == ";":
                self.dot = first
            second, pos = self.parse_address(command, pos)
            if second is None:
                second = len(self.lines)
            start, end = first, second
        else:
            start = end = first

        if start < 0 or end < 0 or start > len(self.lines) or end > len(self.lines) or start > end:
            raise EdError("invalid address")
        return start, end, pos, addressed

    def whole_range(self):
        if not self.lines:
            return 0, 0
        return 1, len(self.lines)

    def default_range(self, command, start, end, addressed):
        if addressed:
            return start, end
        if command in ("w", "W"):
            return self.whole_range()
        if command == "r":
            return len(self.lines), len(self.lines)
        if command == "j":
            if self.dot < len(self.lines):
                return self.dot, self.dot + 1
            return self.dot, self.dot
        if self.dot == 0:
            return 0, 0
        return self.dot, self.dot

    def print_range(self, start, end, numbered=False, literal=False):
        if start == 0 and end == 0:
            return
        for idx in range(start, end + 1):
            line = self.lines[idx - 1]
            if numbered:
                self.out(str(idx) + "\t" + line)
            elif literal:
                self.out(line.replace("$", "\\$") + "$")
            else:
                self.out(line)
        self.set_dot(end)

    def insert_after(self, address, new_lines):
        if not new_lines:
            return
        self.snapshot()
        index = max(0, min(len(self.lines), address))
        self.lines[index:index] = new_lines
        self.dot = index + len(new_lines)

    def delete_range(self, start, end):
        if start == 0 and end == 0:
            return
        self.snapshot()
        self.cut = self.lines[start - 1:end]
        del self.lines[start - 1:end]
        if self.lines:
            self.dot = min(start, len(self.lines))
        else:
            self.dot = 0

    async def command_append(self, address):
        self.insert_after(address, await self.read_text())

    async def command_insert(self, address):
        if address <= 0:
            await self.command_append(0)
        else:
            await self.command_append(address - 1)

    async def command_change(self, start, end):
        text = await self.read_text()
        self.snapshot()
        if start == 0 and end == 0:
            self.lines = text + self.lines
            self.dot = len(text)
        else:
            del self.lines[start - 1:end]
            self.lines[start - 1:start - 1] = text
            self.dot = start + len(text) - 1 if text else min(start, len(self.lines))

    def command_join(self, start, end):
        if start == 0 or start == end:
            return
        self.snapshot()
        joined = "".join(self.lines[start - 1:end])
        self.lines[start - 1:end] = [joined]
        self.dot = start

    def command_move(self, start, end, target):
        if target >= start and target <= end:
            raise EdError("invalid address")
        self.snapshot()
        block = self.lines[start - 1:end]
        del self.lines[start - 1:end]
        if target > end:
            target -= end - start + 1
        index = max(0, min(len(self.lines), target))
        self.lines[index:index] = block
        self.dot = index + len(block)

    def command_copy(self, start, end, target):
        block = self.lines[start - 1:end]
        self.snapshot()
        index = max(0, min(len(self.lines), target))
        self.lines[index:index] = block[:]
        self.dot = index + len(block)

    async def command_read(self, address, path):
        if not path:
            path = self.file
        if not path:
            raise EdError("missing filename")
        data = await _read_all(_abspath(path, self.cwd))
        new_lines = _lines_from_text(data.decode("utf-8", errors="replace"))
        self.insert_after(address, new_lines)
        if not self.silent:
            self.out(str(len(data)))

    async def execute(self, raw):
        start, end, pos, addressed = self.parse_range(raw)
        rest = raw[pos:].strip()

        if not rest:
            if addressed:
                self.print_range(start, end)
            else:
                target = self.dot + 1
                if target > len(self.lines):
                    raise EdError("invalid address")
                self.print_range(target, target)
            return

        command = rest[0]
        arg = rest[1:].strip()

        if command == "#":
            return
        if command == "!":
            raise EdError("shell escapes are not available")
        if command == "P":
            self.prompting = not self.prompting
            return
        if command == "h":
            if self.last_error:
                self.out(self.last_error)
            return
        if command == "H":
            self.verbose = not self.verbose
            return
        if command == "u":
            self.lines, self.undo_lines = self.undo_lines[:], self.lines[:]
            self.set_dot(min(self.dot, len(self.lines)))
            return
        if command == "f":
            if arg:
                self.file = _abspath(arg, self.cwd)
            self.out(self.file)
            return
        if command == "q":
            if self.changed():
                raise EdError("unsaved changes")
            self.running = False
            return
        if command == "Q":
            self.running = False
            return
        if command == "e":
            if not arg:
                raise EdError("missing filename")
            await self.load_file(arg, force=False)
            return
        if command == "E":
            if not arg:
                raise EdError("missing filename")
            await self.load_file(arg, force=True)
            return

        start, end = self.default_range(command, start, end, addressed)

        if command == "a":
            await self.command_append(end)
        elif command == "i":
            await self.command_insert(end)
        elif command == "c":
            await self.command_change(start, end)
        elif command == "d":
            self.delete_range(start, end)
        elif command == "j":
            self.command_join(start, end)
        elif command == "p":
            self.print_range(start, end)
        elif command == "n":
            self.print_range(start, end, numbered=True)
        elif command == "l":
            self.print_range(start, end, literal=True)
        elif command == "=":
            self.out(str(end if addressed else len(self.lines)))
        elif command == "k":
            if not arg or len(arg) != 1 or not arg.isalpha():
                raise EdError("invalid mark")
            self.marks[arg] = end
        elif command == "m":
            target, idx = self.parse_address(arg, 0)
            if target is None or idx != len(arg):
                raise EdError("invalid address")
            self.command_move(start, end, target)
        elif command == "t":
            target, idx = self.parse_address(arg, 0)
            if target is None or idx != len(arg):
                raise EdError("invalid address")
            self.command_copy(start, end, target)
        elif command == "r":
            await self.command_read(end, arg)
        elif command == "w":
            quit_after = False
            if arg.startswith("q"):
                quit_after = True
                arg = arg[1:].strip()
            await self.write_file(arg, start, end, append=False)
            if quit_after:
                self.running = False
        elif command == "W":
            await self.write_file(arg, start, end, append=True)
        elif command == "y":
            self.cut = self.lines[start - 1:end] if start else []
        elif command == "x":
            self.insert_after(end, self.cut[:])
        else:
            raise EdError("unknown command")

    async def parse_args(self):
        idx = 0
        filename = None
        while idx < len(self.argv):
            arg = self.argv[idx]
            if arg in ("-s", "--quiet", "--silent"):
                self.silent = True
            elif arg in ("-v", "--verbose"):
                self.verbose = True
            elif arg == "-p":
                idx += 1
                if idx >= len(self.argv):
                    raise EdError("missing prompt")
                self.prompt = self.argv[idx]
                self.prompting = True
            elif arg.startswith("--prompt="):
                self.prompt = arg[len("--prompt="):]
                self.prompting = True
            elif arg in ("-V", "--version"):
                self.out(self.VERSION)
                self.running = False
            elif arg in ("-h", "--help"):
                self.out("usage: ed [-s] [-v] [-p prompt] [file]")
                self.running = False
            elif arg.startswith("-"):
                raise EdError("unknown option")
            else:
                filename = " ".join(self.argv[idx:])
                break
            idx += 1

        if filename is not None:
            await self.load_file(filename, force=True)

    async def run(self):
        await self.parse_args()
        while self.running:
            prompt = self.prompt if self.prompting else ""
            try:
                raw = await self.read_line(prompt)
                await self.execute(raw)
            except EdError as e:
                self.error(str(e))
            except EOFError:
                self.running = False


async def run(argv=None, cwd="/", write=None, read_char=None):
    if read_char is None:
        if write:
            write("ed needs an interactive shell.\n")
        return
    editor = Editor(argv or [], cwd, write, read_char)
    await editor.run()
