#!/usr/bin/env python3
"""
Smoke test for PythonOS: boots the ISO under QEMU, waits for the TCP REPL
on port 5555 (host) → 5000 (guest), runs a handful of Python expressions,
and verifies expected output.

Usage:
    python3 tests/smoke_test.py [path/to/pythonos.iso]

Exit code: 0 = all tests passed, 1 = failure.
"""

import atexit
import os
import socket
import subprocess
import sys
import tempfile
import time

ISO = sys.argv[1] if len(sys.argv) > 1 else "pythonos.iso"
HOST_PORT = 5555
BOOT_TIMEOUT = 90      # seconds to wait for REPL to become reachable
RECV_TIMEOUT = 15.0    # per-response timeout

QEMU_CMD = [
    "qemu-system-x86_64",
    "-machine", "q35", "-cpu", "qemu64", "-m", "512M",
    "-netdev", f"user,id=net0,hostfwd=tcp::{HOST_PORT}-:5000",
    "-device", "virtio-net-pci,netdev=net0",
    "-device", "intel-hda", "-device", "hda-duplex",
    "-no-reboot", "-no-shutdown",
    "-cdrom", ISO, "-boot", "d",
    "-nographic",
    # serial output captured to a temp file for diagnostics
]

# (expression_to_send, substring_expected_in_response)
TEST_CASES = [
    ("1 + 1\n",                         "2"),
    ("'hello' + ' world'\n",            "hello world"),
    ("type(scheduler).__name__\n",      "Scheduler"),
    ("vfs is not None\n",               "True"),
    ("len([x*x for x in range(5)])\n",  "5"),
    ("1 / 0\n",                         "ZeroDivisionError"),
    ("run('/bin/sysinfo.py')\n",        "PythonOS"),
    ("run('/bin/netstat.py')\n",        "Interface"),
]


def wait_for_port(port: int, timeout: float, proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False  # QEMU exited early
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def recv_until_prompt(sock: socket.socket, prompt: bytes = b">>> ") -> str:
    buf = b""
    sock.settimeout(RECV_TIMEOUT)
    deadline = time.monotonic() + RECV_TIMEOUT
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        if prompt in buf:
            break
    return buf.decode("utf-8", errors="replace")


def run() -> int:
    if not os.path.exists(ISO):
        print(f"[FAIL] ISO not found: {ISO}")
        print("       Run 'make' first to build the kernel image.")
        return 1

    serial_log = tempfile.NamedTemporaryFile(
        mode="w", suffix=".log", prefix="pythonos-serial-",
        delete=False
    )
    serial_log.close()
    atexit.register(lambda: os.unlink(serial_log.name) if os.path.exists(serial_log.name) else None)

    cmd = QEMU_CMD + ["-serial", f"file:{serial_log.name}"]

    print(f"[smoke] Starting QEMU with {ISO} ...")
    print(f"[smoke] Serial log: {serial_log.name}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    def _cleanup():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    try:
        print(f"[smoke] Waiting up to {BOOT_TIMEOUT}s for TCP REPL on port {HOST_PORT} ...")
        if not wait_for_port(HOST_PORT, BOOT_TIMEOUT, proc):
            rc = proc.poll()
            print(f"[FAIL] TCP REPL never became reachable on port {HOST_PORT}")
            if rc is not None:
                print(f"       QEMU exited early with code {rc}")
                stderr = proc.stderr.read().decode("utf-8", errors="replace")
                if stderr.strip():
                    print(f"       QEMU stderr: {stderr.strip()}")
            _print_serial(serial_log.name)
            return 1

        sock = None
        banner = ""
        for attempt in range(1, 4):
            try:
                s = socket.create_connection(("127.0.0.1", HOST_PORT), timeout=5)
            except OSError as e:
                print(f"[smoke] connect attempt {attempt}: {e}; retrying...")
                time.sleep(1.0)
                continue
            try:
                b = recv_until_prompt(s)
                if ">>>" in b:
                    sock = s
                    banner = b
                    break
                s.close()
            except Exception:
                try:
                    s.close()
                except Exception:
                    pass
            print(f"[smoke] attempt {attempt}: no prompt yet, retrying in 1s...")
            time.sleep(1.0)

        if sock is None:
            print(f"[FAIL] No shell prompt after 3 connection attempts")
            _print_serial(serial_log.name)
            return 1

        print(f"[smoke] Connected — shell prompt received.")
        try:
            passed = 0
            failed = 0
            for expr, expected in TEST_CASES:
                sock.sendall(expr.encode())
                response = recv_until_prompt(sock)
                if expected in response:
                    print(f"[PASS] {expr.strip()!r:45s} → found {expected!r}")
                    passed += 1
                else:
                    print(f"[FAIL] {expr.strip()!r:45s} → expected {expected!r}")
                    print(f"       got: {response!r}")
                    failed += 1

            print(f"\n[smoke] {passed} passed, {failed} failed")
            if failed:
                _print_serial(serial_log.name)
            return 0 if failed == 0 else 1

        finally:
            sock.close()
    finally:
        _cleanup()


def _print_serial(path: str) -> None:
    try:
        with open(path) as f:
            content = f.read()
        if content.strip():
            print(f"\n--- serial log ({path}) ---")
            print(content[-4000:] if len(content) > 4000 else content)
            print("--- end serial log ---")
        else:
            print("[smoke] (serial log is empty)")
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(run())
