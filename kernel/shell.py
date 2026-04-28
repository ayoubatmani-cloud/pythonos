"""
kernel.shell — PythonOS interactive shell.

This is not a userspace program running on the OS — it IS the OS talking
to itself. The shell runs as a kernel task, with full access to kernel
internals. exec() of shell input runs in the kernel's own namespace.

Two I/O backends:
  - Console (framebuffer): default when a display is present
  - Serial (COM1):         always mirrored; primary when no display

The shell namespace includes everything a kernel developer needs:
kernel, pci, vfs, scheduler, memory — live objects, not copies.
"""


import asyncio
import traceback
from typing import Callable, Awaitable


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
        self._ns    = self._build_namespace()

    def _build_namespace(self) -> dict:
        import kernel
        import kernel.log as log
        import kernel.net as net
        import kernel.sound as sound
        from kernel.bus.pci import bus as pci
        from kernel.fs.vfs import vfs
        from kernel.scheduler import scheduler
        import kernel.display as display

        ns = {
            "__name__":  "pythonos_shell",
            "kernel":    kernel,
            "log":       log,
            "pci":       pci,
            "vfs":       vfs,
            "net":       net,
            "sound":     sound,
            "scheduler": scheduler,
            "display":   display,
            "help":      lambda: self._help(),
            "ps":        lambda: self._ps(),
            "ls":        lambda path="/": asyncio.ensure_future(self._ls(path)),
            "clear":     lambda: self._clear(),
        }
        return ns

    async def run(self) -> None:
        self._write(f"\nPythonOS kernel shell\n")
        self._write(f"Python {__import__('sys').version}\n")
        self._write(f"Type 'help' for kernel commands.\n\n")
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
        src = self._fixup_source(src)

        try:
            # Try as expression first (so we can print the value)
            try:
                result = eval(compile(src.strip(), "<shell>", "eval"), self._ns)
                if result is not None:
                    # Await coroutines automatically
                    if asyncio.iscoroutine(result):
                        result = await result
                    self._write(repr(result) + "\n")
            except SyntaxError:
                # Not an expression — exec as statement(s)
                exec(compile(src, "<shell>", "exec"), self._ns)
        except SystemExit:
            self._write("Use kernel halt to stop the system.\n")
        except Exception:
            self._write(traceback.format_exc())

        self._write(self.PROMPT)

    @staticmethod
    def _fixup_source(src: str) -> str:
        """Rewrite 'is [not] None/True/False' → '==/!= None/True/False'.

        The frozen Python 3.14 kernel fails to compile these forms; the
        equality equivalents work correctly for singleton constants.
        """
        for kw in ('None', 'True', 'False'):
            src = src.replace(f'is not {kw}', f'!= {kw}')
            src = src.replace(f'is {kw}', f'== {kw}')
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
            "\nKernel shell built-ins:\n"
            "  ps()          — list kernel processes\n"
            "  ls(path)      — list directory\n"
            "  clear()       — clear console\n"
            "  pci           — PCI bus (iterate, .find_by_class())\n"
            "  scheduler     — kernel scheduler\n"
            "  vfs           — virtual filesystem\n"
            "  display       — framebuffer / console\n"
            "  net           — network stack (net.tcp.connect, net.local_ip)\n"
            "  sound         — HDA sound (sound.hda.generate_tone, .write_pcm)\n"
            "\nAll kernel objects are live — changes take effect immediately.\n\n"
        )

    def _ps(self) -> None:
        from kernel.scheduler import scheduler
        for proc in scheduler.ps():
            self._write(f"  {proc.pid:3d}  {proc.name:<20}  {proc.state.name}  "
                        f"ticks={proc.ticks}\n")

    async def _ls(self, path: str) -> None:
        from kernel.fs.vfs import vfs
        try:
            entries = await vfs.readdir(path)
            self._write("  ".join(entries) + "\n")
        except Exception as e:
            self._write(f"ls: {e}\n")

    def _clear(self) -> None:
        from kernel.display.console import console
        if console:
            console.clear()
