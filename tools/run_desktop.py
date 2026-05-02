#!/usr/bin/env python3
"""
Boot PythonOS in GUI mode and auto-launch pythonos_gui so a desktop
window is visible immediately rather than after the user types the
command at the REPL.

Used by `make run-desktop-x86_64` / `make run-desktop-arm64` /
`make run-desktop`. Foregrounds QEMU; Ctrl-C terminates both QEMU and
this launcher.

x86_64: command is sent over the TCP REPL forwarded by the user-mode
        net stack (host port 5560 → guest port 5000).
arm64:  no virtio-net driver yet, so there is no TCP REPL — drive the
        PL011 serial console (QEMU `-serial stdio`) instead by piping
        the command through QEMU's stdin once the shell prompt prints.
"""

import os
import platform
import select
import socket
import subprocess
import sys
import threading
import time


def _macos() -> bool:
    return platform.system() == "Darwin"


def _qemu_cmd_x86_64(iso: str, repl_port: int, display: str, audiodev: str) -> list:
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
        "-display", display,
        "-vga", "std",
        "-serial", "stdio",
    ]


def _qemu_cmd_arm64(elf: str, repl_port: int, display: str, audiodev: str) -> list:
    disk = os.environ.get("PYTHONOS_ARM64_DISK", "disk-arm64.img")
    return [
        "qemu-system-aarch64",
        "-machine", "virt",
        "-cpu", "cortex-a57",
        "-m", "2G",
        "-smp", "2",
        "-no-reboot", "-no-shutdown",
        "-display", display,
        "-device", "ramfb",
        "-serial", "stdio",
        "-device", "virtio-keyboard-device",
        "-device", "virtio-tablet-device",
        "-audiodev", f"{audiodev},id=a",
        "-device", "virtio-sound-device,audiodev=a",
        "-netdev", f"user,id=net1,hostfwd=tcp::{repl_port}-:5000",
        "-device", "virtio-net-device,netdev=net1",
        "-drive", f"if=none,file={disk},format=raw,id=hd0",
        "-device", "virtio-blk-device,drive=hd0",
        "-kernel", elf,
    ]


def _launch_via_tcp(cmd: list, port: int, boot_app: str) -> int:
    """x86_64 path: connect to the forwarded TCP REPL and send the command."""
    proc = subprocess.Popen(cmd)
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

    s.settimeout(4)
    # Ping the shell with bare newlines until we see the prompt — the
    # banner can finish printing several hundred ms after the socket is
    # accepted, and a command sent before that point is silently dropped.
    for _ in range(30):
        time.sleep(0.5)
        try:
            s.sendall(b"\n")
            d = s.recv(4096)
            if b">>>" in d:
                break
        except (TimeoutError, BlockingIOError, OSError):
            continue

    try:
        s.sendall(f"pythonos_gui {boot_app}\n".encode())
        print(f"[run-desktop] sent: pythonos_gui {boot_app}", file=sys.stderr)
    finally:
        s.close()

    return _wait_proc(proc)


def _launch_via_serial(cmd: list, boot_app: str) -> int:
    """arm64 path: pipe the command through QEMU's stdin (PL011 serial)."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )

    sent = threading.Event()
    out_fd = proc.stdout.fileno()
    in_pipe = proc.stdin

    def relay() -> None:
        buf = bytearray()
        deadline = time.time() + 60.0
        while proc.poll() is None:
            r, _, _ = select.select([out_fd], [], [], 0.5)
            if out_fd in r:
                chunk = os.read(out_fd, 4096)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                if not sent.is_set():
                    buf.extend(chunk)
                    if b">>>" in buf:
                        try:
                            in_pipe.write(f"pythonos_gui {boot_app}\n".encode())
                            in_pipe.flush()
                            sent.set()
                            print(f"\n[run-desktop] sent: pythonos_gui {boot_app}",
                                  file=sys.stderr)
                        except OSError as e:
                            print(f"[run-desktop] write failed: {e}", file=sys.stderr)
                            return
                        buf.clear()
            elif not sent.is_set() and time.time() > deadline:
                print("[run-desktop] timed out waiting for kernel prompt",
                      file=sys.stderr)
                return

    t = threading.Thread(target=relay, daemon=True)
    t.start()
    return _wait_proc(proc)


def _wait_proc(proc: subprocess.Popen) -> int:
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


def main() -> int:
    image = sys.argv[1] if len(sys.argv) > 1 else "pythonos.iso"
    arch = os.environ.get("PYTHONOS_DESKTOP_ARCH")
    if arch is None:
        arch = "arm64" if image.endswith(".elf") else "x86_64"

    default_port = "5560" if arch == "x86_64" else "5561"
    port = int(os.environ.get("PYTHONOS_DESKTOP_PORT", default_port))
    boot_app = os.environ.get("PYTHONOS_DESKTOP_APP", "bouncing_ball")

    display  = os.environ.get("QEMU_DISPLAY",  "cocoa" if _macos() else "sdl")
    audiodev = os.environ.get("QEMU_AUDIODEV", "coreaudio" if _macos() else "sdl")

    if not os.path.exists(image):
        print(f"run-desktop: {image} not found; run `make` first", file=sys.stderr)
        return 1

    print(f"[run-desktop] booting {image} (arch={arch}) with -display {display}, "
          f"will auto-launch pythonos_gui {boot_app} once the shell prompt is ready",
          file=sys.stderr)

    if arch == "arm64":
        cmd = _qemu_cmd_arm64(image, port, display, audiodev)
        return _launch_via_serial(cmd, boot_app)
    cmd = _qemu_cmd_x86_64(image, port, display, audiodev)
    return _launch_via_tcp(cmd, port, boot_app)


if __name__ == "__main__":
    sys.exit(main())
