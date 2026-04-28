"""
kernel.shell — PythonOS interactive shell.

This is not a userspace program running on the OS — it IS the OS talking
to itself. The shell runs as a kernel task, with full access to kernel
internals. exec() of shell input runs in the kernel's own namespace.

Two I/O backends:
  - Console (framebuffer): default when a display is present
  - Serial (COM1):         always mirrored; primary when no display

Command dispatch
----------------
Bare words that are not Python names are looked up as /bin/<word>.py and
executed automatically, so the user can type:

    sysinfo
    ls /tmp
    cd /bin
    ps

Scripts receive two extra namespace variables:
  argv  — list of string arguments (may be empty)
  cwd   — current working directory string

Top-level `await` is supported in scripts via PyCF_ALLOW_TOP_LEVEL_AWAIT,
so scripts can call async VFS operations directly:

    entries = await vfs.readdir(path)

The `sh()` built-in provides the same dispatch programmatically:

    sh('ls /tmp')
    sh('cp /bin/sysinfo.py /tmp/copy.py')
"""


import asyncio
import traceback
from typing import Callable, Awaitable


_PYCF_ALLOW_TOP_LEVEL_AWAIT = 0x2000


class Shell:
    PROMPT      = ">>> "
    CONT_PROMPT = "... "

    def __init__(self,
                 read_char: Callable[[], Awaitable[str]],
                 write: Callable[[str], None]) -> None:
        self._read  = read_char
        self._write = write
        self._buf   = ""         # accumulated input line
        self._block = ""         # accumulated multi-line block
        self._cwd   = "/"        # current working directory
        self._ns    = self._build_namespace()

    def _build_namespace(self) -> dict:
        import kernel
        import kernel.log as log
        import kernel.net as net
        import kernel.sound as sound
        from kernel.bus.pci import bus as pci
        from kernel.fs.vfs import vfs, OpenFlags
        from kernel.scheduler import scheduler
        import kernel.display as display

        ns = {
            "__name__":  "pythonos_shell",
            "kernel":    kernel,
            "log":       log,
            "pci":       pci,
            "vfs":       vfs,
            "OpenFlags": OpenFlags,
            "net":       net,
            "sound":     sound,
            "scheduler": scheduler,
            "display":   display,
            "help":      lambda: self._help(),
            "clear":     lambda: self._clear(),
            "sh":        lambda cmd=None: self._sh(cmd),
            "run":       lambda path: self._run(path),
            "print":     lambda *args, sep=" ", end="\n":
                             self._write(sep.join(str(a) for a in args) + end),
            "cwd":       "/",
        }
        return ns

    async def run(self) -> None:
        self._write("\nPythonOS kernel shell\n")
        self._write("Python " + __import__('sys').version + "\n")
        self._write("Type 'help' for help.\n")
        self._write("Commands: ls ps pwd cd cat cp mv ftp vi sysinfo netstat\n")
        self._write("Helpers: sh()  sh('cmd args')  run('/path')  clear()\n\n")
        self._write(self.PROMPT)

        while True:
            ch = await self._read()

            if ch == '\n':
                self._write('\n')
                line = self._buf
                self._buf = ""
                await self._process_line(line)
            elif ch == '\b' or ord(ch) == 127:
                if self._buf:
                    self._buf = self._buf[:-1]
                    self._write('\b \b')
            else:
                self._buf += ch
                self._write(ch)   # echo

    async def _process_line(self, line: str) -> None:
        if not line.strip() and not self._block:
            self._write(self.PROMPT)
            return

        self._block += line + "\n"

        # Check if we need more input (open block)
        needs_more = self._is_incomplete(self._block)

        if needs_more:
            self._write(self.CONT_PROMPT)
            return

        src = self._block
        self._block = ""

        # Shell command dispatch: bare word(s) not in Python namespace → /bin/<name>.py
        if await self._try_shell_dispatch(src):
            self._write(self.PROMPT)
            return

        src = self._fixup_source(src)

        try:
            # Try as expression first (so we can print the value)
            try:
                result = eval(compile(src.strip(), "<shell>", "eval"), self._ns)
                if asyncio.iscoroutine(result):
                    result = await result
                if result is not None:
                    self._write(repr(result) + "\n")
            except SyntaxError:
                # Not an expression — exec as statement(s)
                exec(compile(src, "<shell>", "exec"), self._ns)
        except SystemExit:
            self._write("Use kernel halt to stop the system.\n")
        except Exception:
            self._write(traceback.format_exc())

        self._write(self.PROMPT)

    # ── Shell command dispatch ────────────────────────────────────────────────

    async def _try_shell_dispatch(self, src: str) -> bool:
        """Dispatch a bare command name to /bin/<name>.py.  Returns True if handled."""
        line = src.strip()
        # Only dispatch single-line input that looks like a shell invocation
        if not line or '\n' in line:
            return False
        parts = line.split()
        name = parts[0]
        # Must be a plain identifier (no dots, parens, operators…)
        if not name.isidentifier():
            return False
        if name == "help" and len(parts) == 1:
            self._help()
            return True
        # Skip Python keywords
        try:
            import keyword
            if keyword.iskeyword(name):
                return False
        except ImportError:
            pass
        # Don't shadow names already live in the Python namespace
        if name in self._ns:
            return False
        return await self._run_script("/bin/" + name + ".py", parts[1:])

    async def _run_script(self, path: str, args: list) -> bool:
        """Load and exec a /bin script.  Returns False if the file is not found."""
        from kernel.fs.vfs import vfs
        try:
            fd = await vfs.open(path)
        except Exception:
            return False

        chunks = []
        while True:
            chunk = await vfs.read(fd, 4096)
            if not chunk:
                break
            chunks.append(chunk)
        vfs.close(fd)

        src = b"".join(chunks).decode("utf-8")

        if await self._try_precompiled_script(path, args, src):
            return True

        src = self._fixup_source(src)

        # Give scripts their own local view; argv and cwd are script-visible
        local_ns = dict(self._ns)
        local_ns['argv'] = args
        local_ns['cwd']  = self._cwd
        local_ns['_write'] = self._write

        try:
            # PyCF_ALLOW_TOP_LEVEL_AWAIT lets scripts use `await` at module level
            code  = compile(src, path, "exec", flags=_PYCF_ALLOW_TOP_LEVEL_AWAIT)
            coro  = eval(code, local_ns)
            if asyncio.iscoroutine(coro):
                await coro
        except Exception:
            self._write(traceback.format_exc())

        # Propagate cwd changes made by the script (e.g. cd.py sets cwd = target)
        self._update_cwd(local_ns.get('cwd'))

        return True

    async def _try_precompiled_script(self, path: str, args: list, src: str) -> bool:
        """Run known seeded scripts from frozen bytecode when available."""
        if path.startswith("/bin/") and path.endswith(".py") and "/" not in path[len("/bin/"):]:
            try:
                import kernel.commands as commands
                name = path[len("/bin/"):]
                if commands.SCRIPTS.get(name) != src:
                    return False
                func = getattr(commands, name[:-3], None)
                if func is None:
                    return False
                if name == "vi.py":
                    result = func(args, self._cwd, self._write, self._read)
                else:
                    result = func(args, self._cwd, self._write)
                if asyncio.iscoroutine(result):
                    result = await result
                self._update_cwd(result)
                return True
            except Exception:
                self._write(traceback.format_exc())
                return True

        if path.startswith("/examples/") and path.endswith(".py"):
            try:
                from kernel.frozen_sources import SOURCES
                if SOURCES.get(path) != src:
                    return False
                mod_name = "examples." + path[len("/examples/"):-3].replace("/", ".")
                import sys
                sys.modules.pop(mod_name, None)
                mod = __import__(mod_name, fromlist=["main"])
                main = getattr(mod, "main", None)
                if main is None:
                    self._write("run: " + path + ": no main() in frozen example\n")
                    return True
                result = main(
                    argv=args,
                    cwd=self._cwd,
                    read_char=self._read,
                    write=self._write,
                )
                if asyncio.iscoroutine(result):
                    result = await result
                self._update_cwd(result)
                return True
            except Exception:
                self._write(traceback.format_exc())
                return True

        return False

    def _update_cwd(self, new_cwd) -> None:
        if isinstance(new_cwd, str) and new_cwd != self._cwd:
            self._cwd = new_cwd
            self._ns['cwd'] = new_cwd

    async def _sh(self, cmd=None) -> None:
        """sh() → interactive sub-shell.  sh('cmd args') → dispatch to /bin/."""
        if cmd is None:
            await self._sh_repl()
            return
        parts = cmd.strip().split()
        if not parts:
            return
        await self._run_sh_parts(parts)

    async def _sh_repl(self) -> None:
        """Interactive sub-shell: $ prompt, command dispatch, 'exit' to return."""
        SH = "$ "
        self._write(SH)
        buf = ""
        while True:
            ch = await self._read()
            if ch == '\n':
                self._write('\n')
                line = buf.strip()
                buf = ""
                if line == 'exit':
                    return
                if line:
                    parts = line.split()
                    await self._run_sh_parts(parts)
                self._write(SH)
            elif ch == '\b' or ord(ch) == 127:
                if buf:
                    buf = buf[:-1]
                    self._write('\b \b')
            else:
                buf += ch
                self._write(ch)

    async def _run_sh_parts(self, parts: list[str]) -> None:
        name = parts[0]
        args = parts[1:]

        path = self._sh_script_path(name)
        if path is not None:
            if not await self._run_script(path, args):
                self._write("sh: " + name + ": not found\n")
            return

        if not await self._run_script("/bin/" + name + ".py", args):
            self._write("sh: " + name + ": command not found\n")

    def _sh_script_path(self, name: str) -> str | None:
        if "/" not in name or not name.endswith(".py"):
            return None
        if name.startswith("/"):
            target = name
        else:
            target = self._cwd.rstrip("/") + "/" + name

        parts = []
        for seg in target.split("/"):
            if seg == "..":
                if parts:
                    parts.pop()
            elif seg and seg != ".":
                parts.append(seg)
        return "/" + "/".join(parts)

    async def _run(self, path: str) -> None:
        """run('/full/path/to/script.py') — execute any VFS file by absolute path."""
        if not await self._run_script(path, []):
            self._write("run: " + path + ": not found\n")

    # ── Source fixups for frozen Python 3.14 ─────────────────────────────────

    @staticmethod
    def _fixup_source(src: str) -> str:
        """Rewrite 'is [not] None/True/False' → '==/!= None/True/False'.

        The frozen Python 3.14 kernel fails to compile these forms; the
        equality equivalents work correctly for singleton constants.
        """
        for kw in ('None', 'True', 'False'):
            src = src.replace('is not ' + kw, '!= ' + kw)
            src = src.replace('is ' + kw, '== ' + kw)
        return src

    @staticmethod
    def _is_incomplete(src: str) -> bool:
        try:
            import codeop
            result = codeop.compile_command(src, "<shell>", "exec")
            return result is None   # None = need more input
        except SyntaxError:
            return False
        except Exception:
            # codeop unavailable (e.g. __future__ not frozen yet); assume complete
            return False

    # ── Built-in shell commands ───────────────────────────────────────────────

    def _help(self) -> None:
        self._write(
            "\nCommands (type bare name or sh('cmd args')):\n"
            "  ls [path]      — list directory\n"
            "  ps             — kernel task list\n"
            "  pwd            — print working directory\n"
            "  cd [path]      — change directory\n"
            "  cat FILE [...] — print file contents\n"
            "  cp SRC DST     — copy file\n"
            "  mv SRC DST     — move / rename file\n"
            "  ftp get/put    — copy files over TCP\n"
            "  vi [path]      — small Python line editor\n"
            "  sysinfo        — system overview\n"
            "  netstat        — network status\n"
            "  clear()        — clear framebuffer console\n"
            "  run('/path')   — run script by absolute path\n"
            "  sh()           — enter shell sub-REPL\n"
            "  sh('cmd args') — same, with shell-style argument splitting\n"
            "  /path/file.py  — in sh(), run a Python file directly\n"
            "\nLive kernel objects:\n"
            "  pci        — PCI bus: list(pci), pci.find_by_class(0x0200)\n"
            "  scheduler  — task scheduler: scheduler.ps()\n"
            "  vfs        — filesystem: await vfs.readdir('/')\n"
            "  display    — framebuffer / console\n"
            "  net        — network: net.local_ip\n"
            "  sound      — HDA audio: sound.hda.generate_tone(freq, ms)\n"
            "  cwd        — current working directory (string)\n\n"
        )

    def _clear(self) -> None:
        from kernel.display.console import console
        if console:
            console.clear()
