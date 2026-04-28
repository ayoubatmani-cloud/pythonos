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
    await _write_all(dst, await _read_all(src))
    await vfs.unlink(src)


async def vi(argv: list[str], cwd: str, write, read_char=None) -> None:
    from examples import mini_vi
    await mini_vi.main(argv=argv, cwd=cwd, read_char=read_char, write=write)
