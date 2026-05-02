#!/usr/bin/env python3
"""
Boot the x86 ISO in headless GUI mode and verify the GUI substrate
came up cleanly.

Boots with `-display none -vga std` so QEMU still emulates the bochs-
VBE adapter (GRUB negotiates a framebuffer through multiboot2) but no
host SDL window opens. Connects to the kernel's TCP REPL and exercises:

    1. The kernel's serial log shows  "framebuffer console ready"
       and "GUI input ready (PS/2)".
    2. `import sdl2` resolves without ImportError.
    3. `examples/sdl_hello.py` runs and prints "sdl_hello: ok".
    4. The `pythonos_gui` command is reachable (validated by listing
       /bin which now contains pythonos_gui.py).

The default `tests/smoke_test.py` is unchanged and remains the gate
for `make test`. This new test runs under `make test-gui-x86_64`.
"""

import os
import socket
import subprocess
import sys
import time

ISO = sys.argv[1] if len(sys.argv) > 1 else "pythonos.iso"
PORT = int(os.environ.get("PYTHONOS_GUI_HOST_PORT", "5559"))
BOOT_TIMEOUT = float(os.environ.get("PYTHONOS_GUI_BOOT_TIMEOUT", "30"))

SERIAL_LOG = "/tmp/pythonos-gui-smoke.log"


def _qemu_cmd():
    return [
        "qemu-system-x86_64",
        "-machine", "q35",
        "-cpu", "qemu64",
        "-m", "2G",
        "-smp", "2",
        "-netdev", f"user,id=net0,hostfwd=tcp::{PORT}-:5000",
        "-device", "virtio-net-pci,netdev=net0",
        "-device", "intel-hda",
        "-device", "hda-duplex",
        "-no-reboot", "-no-shutdown",
        "-cdrom", ISO,
        "-boot", "d",
        "-display", "none",
        "-vga", "std",
        "-serial", f"file:{SERIAL_LOG}",
    ]


def _connect(deadline: float) -> socket.socket:
    while time.time() < deadline:
        try:
            s = socket.create_connection(("localhost", PORT), timeout=2)
            s.settimeout(8)
            return s
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"GUI smoke: TCP REPL on {PORT} never came up")


def _send(s: socket.socket, line: str, wait: float = 2.5) -> str:
    s.sendall((line + "\n").encode())
    time.sleep(wait)
    chunks = []
    s.settimeout(0.4)
    try:
        while True:
            data = s.recv(8192)
            if not data:
                break
            chunks.append(data)
    except (TimeoutError, BlockingIOError):
        pass
    s.settimeout(8)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _drain(s: socket.socket, wait: float = 1.0) -> None:
    time.sleep(wait)
    s.settimeout(0.3)
    try:
        while True:
            d = s.recv(8192)
            if not d:
                break
    except (TimeoutError, BlockingIOError):
        pass
    s.settimeout(8)


def main() -> int:
    if os.path.exists(SERIAL_LOG):
        os.remove(SERIAL_LOG)

    print(f"[gui-smoke] booting {ISO} headless+vga-std on TCP {PORT}")
    proc = subprocess.Popen(_qemu_cmd(),
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + BOOT_TIMEOUT
        s = _connect(deadline)
        # Wait for the prompt by sending a sentinel and watching for ">>> ".
        for _ in range(60):
            time.sleep(0.5)
            try:
                s.sendall(b"\n")
            except OSError:
                break
            try:
                s.settimeout(0.4)
                d = s.recv(4096)
                if b">>>" in d:
                    break
            except (TimeoutError, BlockingIOError):
                continue
            finally:
                s.settimeout(8)
        _drain(s, 0.5)

        passes = 0
        fails  = 0

        def check(name: str, ok: bool, detail: str = "") -> None:
            nonlocal passes, fails
            if ok:
                print(f"[PASS] {name}{(' — ' + detail) if detail else ''}")
                passes += 1
            else:
                print(f"[FAIL] {name}{(' — ' + detail) if detail else ''}")
                fails += 1

        # 1. Examples sdl_hello runs end-to-end via the sdl2 shim.
        out = _send(s, "run('/examples/sdl_hello.py')", wait=4.5)
        check("examples/sdl_hello.py runs", "sdl_hello: ok" in out,
              detail=out.splitlines()[-1] if out.strip() else "(empty)")

        # 2. /bin/pythonos_gui.py is registered.
        out = _send(s, "sh('ls /bin')", wait=3.0)
        check("/bin/pythonos_gui.py present",
              "pythonos_gui" in out,
              detail="present" if "pythonos_gui" in out else "missing")

        # 3. Mixer + sdl2 sdlmixer constants reachable.
        out = _send(s, "__import__('sdl2').MIX_DEFAULT_FREQUENCY", wait=2.5)
        check("sdl2.MIX_DEFAULT_FREQUENCY reachable",
              "44100" in out,
              detail=(out.strip().splitlines()[-1] if out.strip() else ""))

        # 4. Compositor singleton accessible (don't run it — it'd spawn tasks).
        out = _send(s, "type(__import__('kernel.gui.compositor', fromlist=['compositor']).compositor).__name__", wait=2.5)
        check("kernel.gui.compositor.Compositor importable",
              "Compositor" in out,
              detail=(out.strip().splitlines()[-1] if out.strip() else ""))

        # Inspect serial log markers.
        try:
            with open(SERIAL_LOG, "r", encoding="utf-8", errors="replace") as f:
                serial = f.read()
        except OSError:
            serial = ""

        check("serial: framebuffer console ready",
              "framebuffer console ready" in serial)
        check("serial: GUI input ready (PS/2)",
              "GUI input ready (PS/2)" in serial)

        s.close()
        print(f"\n[gui-smoke] {passes} passed, {fails} failed")
        return 0 if fails == 0 else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
