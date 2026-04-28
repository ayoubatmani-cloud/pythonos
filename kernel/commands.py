"""
kernel.commands — Precompiled implementations for the seeded /bin commands.

The TmpFS still exposes small Python launcher scripts in /bin, but the shell
dispatches these functions directly while the runtime compiler is limited.
"""

from kernel.fs.vfs import vfs, OpenFlags
from kernel.net.ip import ip_str
from kernel.scheduler import scheduler


SCRIPTS = {
    "sysinfo.py": (
        "from kernel import commands\n"
        "await commands.sysinfo(argv, cwd, _write)\n"
    ),
    "netstat.py": (
        "from kernel import commands\n"
        "await commands.netstat(argv, cwd, _write)\n"
    ),
    "ls.py": (
        "from kernel import commands\n"
        "await commands.ls(argv, cwd, _write)\n"
    ),
    "ps.py": (
        "from kernel import commands\n"
        "await commands.ps(argv, cwd, _write)\n"
    ),
    "pwd.py": (
        "from kernel import commands\n"
        "await commands.pwd(argv, cwd, _write)\n"
    ),
    "cd.py": (
        "from kernel import commands\n"
        "cwd = await commands.cd(argv, cwd, _write)\n"
    ),
    "cp.py": (
        "from kernel import commands\n"
        "await commands.cp(argv, cwd, _write)\n"
    ),
    "mv.py": (
        "from kernel import commands\n"
        "await commands.mv(argv, cwd, _write)\n"
    ),
    "ftp.py": (
        "from kernel import commands\n"
        "await commands.ftp(argv, cwd, _write)\n"
    ),
    "vi.py": (
        "from kernel import commands\n"
        "await commands.vi(argv, cwd, _write)\n"
    ),
}


def _line(write, text: str = "") -> None:
    write(text + "\n")


def _abspath(path: str, cwd: str) -> str:
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


async def sysinfo(argv: list[str], cwd: str, write) -> None:
    _line(write, "PythonOS")
    tasks = list(scheduler.ps())
    _line(write, "Scheduler: " + str(len(tasks)) + " tasks")
    _line(write, "cwd: " + cwd)


async def netstat(argv: list[str], cwd: str, write) -> None:
    from kernel.net import stack
    _line(write, "Interface   local_ip")
    _line(write, "lo          127.0.0.1")
    _line(write, "eth0        " + ip_str(stack.local_ip))


async def ls(argv: list[str], cwd: str, write) -> None:
    path = _abspath(argv[0], cwd) if argv else cwd
    entries = await vfs.readdir(path)
    _line(write, "  ".join(entries))


async def ps(argv: list[str], cwd: str, write) -> None:
    for p in scheduler.ps():
        pid = str(p.pid).rjust(4)
        name = p.name.ljust(22)
        _line(write, pid + "  " + name + "  " + p.state.name)


async def pwd(argv: list[str], cwd: str, write) -> None:
    _line(write, cwd)


async def cd(argv: list[str], cwd: str, write) -> str:
    target = _abspath(argv[0], cwd) if argv else "/"
    await vfs.readdir(target)
    return target


async def _read_all(path: str) -> bytes:
    fd = await vfs.open(path)
    data = b""
    while True:
        chunk = await vfs.read(fd, 4096)
        if not chunk:
            break
        data = data + chunk
    vfs.close(fd)
    return data


async def _write_all(path: str, data: bytes) -> None:
    fd = await vfs.open(path, OpenFlags.WRONLY | OpenFlags.CREAT | OpenFlags.TRUNC)
    await vfs.write(fd, data)
    vfs.close(fd)


async def cp(argv: list[str], cwd: str, write) -> None:
    if len(argv) < 2:
        _line(write, "usage: cp SRC DST")
        return
    src = _abspath(argv[0], cwd)
    dst = _abspath(argv[1], cwd)
    await _write_all(dst, await _read_all(src))


async def mv(argv: list[str], cwd: str, write) -> None:
    if len(argv) < 2:
        _line(write, "usage: mv SRC DST")
        return
    src = _abspath(argv[0], cwd)
    dst = _abspath(argv[1], cwd)
    if src == dst:
        return
    await _write_all(dst, await _read_all(src))
    await vfs.unlink(src)


def _ftp_usage(write) -> None:
    _line(write, "usage: ftp get DST [PORT]")
    _line(write, "       ftp put SRC [HOST] [PORT]")
    _line(write, "       ftp recv DST [PORT]")
    _line(write, "       ftp send SRC [HOST] [PORT]")
    _line(write, "get/recv: listen for one TCP stream and save it to DST")
    _line(write, "put/send: connect to HOST:PORT and send SRC")
    _line(write, "defaults: PORT=7000 for get, HOST=10.0.2.2 PORT=7001 for put")


def _parse_port(value: str, write):
    try:
        port = int(value)
    except ValueError:
        _line(write, "ftp: invalid port: " + value)
        return None
    if port < 1 or port > 65535:
        _line(write, "ftp: port out of range: " + value)
        return None
    return port


async def _ftp_get(path: str, port: int, write) -> None:
    from kernel.net import stack
    from kernel.net.tcp import tcp

    fd = await vfs.open(path, OpenFlags.WRONLY | OpenFlags.CREAT | OpenFlags.TRUNC)
    conn = None
    listener = await tcp.listen(port)
    _line(write, "ftp: listening on " + ip_str(stack.local_ip) + ":" + str(port))
    _line(write, "ftp: waiting for one incoming file stream")

    total = 0
    try:
        conn = await listener.accept()
        while True:
            chunk = await conn.recv(1024)
            if not chunk:
                break
            await vfs.write(fd, chunk)
            total += len(chunk)
    finally:
        vfs.close(fd)
        if conn is not None:
            conn.close()

    _line(write, "ftp: saved " + str(total) + " bytes to " + path)


async def _ftp_put(path: str, host: str, port: int, write) -> None:
    from kernel.net.tcp import tcp

    fd = await vfs.open(path)
    conn = None
    _line(write, "ftp: connecting to " + host + ":" + str(port))
    total = 0
    try:
        conn = await tcp.connect(host, port)
        while True:
            chunk = await vfs.read(fd, 1024)
            if not chunk:
                break
            await conn.send(chunk)
            total += len(chunk)
    finally:
        vfs.close(fd)
        if conn is not None:
            conn.close()

    _line(write, "ftp: sent " + str(total) + " bytes from " + path)


async def ftp(argv: list[str], cwd: str, write) -> None:
    if not argv or argv[0] in ("help", "-h", "--help"):
        _ftp_usage(write)
        return

    op = argv[0]
    if op in ("get", "recv"):
        if len(argv) < 2 or len(argv) > 3:
            _ftp_usage(write)
            return
        path = _abspath(argv[1], cwd)
        port = 7000
        if len(argv) == 3:
            parsed = _parse_port(argv[2], write)
            if parsed is None:
                return
            port = parsed
        await _ftp_get(path, port, write)
        return

    if op in ("put", "send"):
        if len(argv) < 2 or len(argv) > 4:
            _ftp_usage(write)
            return
        path = _abspath(argv[1], cwd)
        host = argv[2] if len(argv) >= 3 else "10.0.2.2"
        port = 7001
        if len(argv) == 4:
            parsed = _parse_port(argv[3], write)
            if parsed is None:
                return
            port = parsed
        await _ftp_put(path, host, port, write)
        return

    _line(write, "ftp: unknown operation: " + op)
    _ftp_usage(write)


async def vi(argv: list[str], cwd: str, write, read_char=None) -> None:
    from examples import mini_vi
    await mini_vi.main(argv=argv, cwd=cwd, read_char=read_char, write=write)
