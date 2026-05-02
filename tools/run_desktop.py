#!/usr/bin/env python3
"""
Boot PythonOS in GUI mode and auto-launch pythonos_gui so a desktop
window is visible immediately rather than after the user types the
command at the REPL.

Used by `make run-desktop-x86_64` / `make run-desktop`. Foregrounds
QEMU; Ctrl-C terminates both QEMU and this launcher.
"""

import os
import socket
import subprocess
import sys
import time


def _qemu_cmd(iso: str, repl_port: int) -> list:
    return [
        "qemu-system-x86_64",
        "-machine", "q35",
        "-cpu", "qemu64",
        "-m", "2G",
        "-smp", "2",
        "-netdev", f"user,id=net0,hostfwd=tcp::{repl_port}-:5000",
        "-device", "virtio-net-pci,netdev=net0",
        "-device", "intel-hda",
        "-device", "hda-duplex",
        "-no-reboot", "-no-shutdown",
        "-cdrom", iso,
        "-boot", "d",
        "-display", "sdl",
        "-vga", "std",
        "-serial", "stdio",
    ]


def main() -> int:
    iso = sys.argv[1] if len(sys.argv) > 1 else "pythonos.iso"
    port = int(os.environ.get("PYTHONOS_DESKTOP_PORT", "5560"))
    boot_app = os.environ.get("PYTHONOS_DESKTOP_APP", "bouncing_ball")

    if not os.path.exists(iso):
        print(f"run-desktop: {iso} not found; run `make` first", file=sys.stderr)
        return 1

    print(f"[run-desktop] booting {iso} with -display sdl, will auto-launch "
          f"pythonos_gui {boot_app} once REPL is up", file=sys.stderr)

    proc = subprocess.Popen(_qemu_cmd(iso, port))

    # Race the kernel boot against a 30 s deadline. Connect to the TCP
    # REPL, send `pythonos_gui <app>`, and let QEMU keep running.
    deadline = time.time() + 30.0
    s = None
    while time.time() < deadline and s is None:
        try:
            s = socket.create_connection(("localhost", port), timeout=2)
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("run-desktop: kernel REPL never came up", file=sys.stderr)
        proc.terminate()
        return 2

    try:
        time.sleep(0.5)
        try:
            s.recv(8192)
        except (TimeoutError, BlockingIOError):
            pass
        cmd = (f"pythonos_gui {boot_app}\n").encode()
        s.sendall(cmd)
        print(f"[run-desktop] sent: pythonos_gui {boot_app}", file=sys.stderr)
    finally:
        s.close()

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 130
    return proc.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
