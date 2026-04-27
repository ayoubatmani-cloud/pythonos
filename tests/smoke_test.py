#!/usr/bin/env python3
"""
Smoke test for PythonOS: boots the ISO under QEMU, waits for the TCP REPL
on port 5555 (host) → 5000 (guest), runs a handful of Python expressions,
and verifies expected output.

Usage:
    python3 tests/smoke_test.py [path/to/pythonos.iso]

Exit code: 0 = all tests passed, 1 = failure.
"""

import socket
import subprocess
import sys
import time

ISO = sys.argv[1] if len(sys.argv) > 1 else "pythonos.iso"
HOST_PORT = 5555
BOOT_TIMEOUT = 60      # seconds to wait for REPL to become reachable
RECV_TIMEOUT = 10.0    # per-response timeout

QEMU_CMD = [
    "qemu-system-x86_64",
    "-machine", "q35", "-cpu", "qemu64", "-m", "512M",
    "-netdev", f"user,id=net0,hostfwd=tcp::{HOST_PORT}-:5000",
    "-device", "virtio-net-pci,netdev=net0",
    "-device", "intel-hda", "-device", "hda-duplex",
    "-no-reboot", "-no-shutdown",
    "-cdrom", ISO, "-boot", "d",
    "-nographic", "-serial", "file:/dev/null",
]

# (expression_to_send, substring_expected_in_response)
TEST_CASES = [
    ("1 + 1\n",                         "2"),
    ("'hello' + ' world'\n",            "hello world"),
    ("type(scheduler).__name__\n",      "Scheduler"),
    ("vfs is not None\n",               "True"),
    ("len([x*x for x in range(5)])\n",  "5"),
    ("1 / 0\n",                         "ZeroDivisionError"),
]


def wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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
    print(f"[smoke] Starting QEMU with {ISO} ...")
    proc = subprocess.Popen(
        QEMU_CMD,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        print(f"[smoke] Waiting up to {BOOT_TIMEOUT}s for TCP REPL on port {HOST_PORT} ...")
        if not wait_for_port(HOST_PORT, BOOT_TIMEOUT):
            print(f"[FAIL] TCP REPL never became reachable on port {HOST_PORT}")
            return 1

        sock = socket.create_connection(("127.0.0.1", HOST_PORT), timeout=5)
        try:
            # Consume the initial banner / prompt
            banner = recv_until_prompt(sock)
            if ">>>" not in banner:
                print(f"[FAIL] No shell prompt in banner: {banner!r}")
                return 1
            print(f"[smoke] Connected. Banner received.")

            passed = 0
            failed = 0
            for expr, expected in TEST_CASES:
                sock.sendall(expr.encode())
                response = recv_until_prompt(sock)
                if expected in response:
                    print(f"[PASS] {expr.strip()!r:45s} → found {expected!r}")
                    passed += 1
                else:
                    print(f"[FAIL] {expr.strip()!r:45s} → expected {expected!r}, got {response!r}")
                    failed += 1

            print(f"\n[smoke] {passed} passed, {failed} failed")
            return 0 if failed == 0 else 1

        finally:
            sock.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(run())
