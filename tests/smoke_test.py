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
HOST_PORT = int(os.environ.get("PYTHONOS_HOST_PORT", "5555"))
FILE_HOST_PORT = int(os.environ.get("PYTHONOS_FILE_PORT", "17000"))
BOOT_TIMEOUT = 90      # seconds to wait for REPL to become reachable
RECV_TIMEOUT = 15.0    # per-response timeout

QEMU_CMD = [
    "qemu-system-x86_64",
    "-machine", "q35", "-cpu", "qemu64", "-m", "2G",
    "-netdev", f"user,id=net0,hostfwd=tcp::{HOST_PORT}-:5000,hostfwd=tcp::{FILE_HOST_PORT}-:7000",
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
    ("sh('ps')\n",                      "kshell"),
    ("sh('/bin/sysinfo.py')\n",          "PythonOS"),
    ("ls /bin\n",                       "ed.py"),
    ("cat /examples/README.txt\n",      "PythonOS examples"),
    ("ftp\n",                           "usage: ftp get DST"),
    ("ftp get /tmp/repl-port.txt 5000\n", "ftp: port already in use: 5000"),
    ("ls /examples\n",                  "hello_kernel.py"),
    ("vi\n",                            "NameError"),
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
            for label, expected in [
                ("banner lists cat", "Commands: ls ps pwd cd cat"),
                ("banner lists sh()", "Helpers: sh()"),
            ]:
                if expected in banner:
                    print(f"[PASS] {label:45s} → found {expected!r}")
                    passed += 1
                else:
                    print(f"[FAIL] {label:45s} → expected {expected!r}")
                    print(f"       got: {banner!r}")
                    failed += 1

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

            if run_file_copy_test(sock):
                passed += 1
            else:
                failed += 1

            if run_ed_editor_test(sock):
                passed += 1
            else:
                failed += 1

            example_passed, example_failed = run_example_tests(sock)
            passed += example_passed
            failed += example_failed

            print(f"\n[smoke] {passed} passed, {failed} failed")
            if failed:
                _print_serial(serial_log.name)
            return 0 if failed == 0 else 1

        finally:
            sock.close()
    finally:
        _cleanup()


def run_file_copy_test(sock: socket.socket) -> bool:
    payload = b"hello from host via ftp\n"
    target = "/tmp/ftp-in.txt"

    if not run_ftp_get_once(sock, target, payload):
        return False
    if not run_ftp_get_once(sock, "/tmp/ftp-in-2.txt", b"second ftp get\n"):
        return False
    if not run_ftp_put_once(sock, target, payload):
        return False

    print("[PASS] 'ftp get/put file copy'                   → round-trip bytes matched")
    return True


def run_ed_editor_test(sock: socket.socket) -> bool:
    target = "/tmp/ed-test.txt"
    script = (
        "ed -s " + target + "\n"
        "a\n"
        "alpha\n"
        "beta\n"
        ".\n"
        ",p\n"
        "1,2n\n"
        "w\n"
        "Q\n"
    )

    sock.sendall(script.encode())
    response = recv_until_prompt(sock)
    if "alpha" not in response or "beta" not in response or "2\tbeta" not in response:
        print("[FAIL] 'ed append/print/write' did not show expected buffer output")
        print(f"       got: {response!r}")
        return False

    sock.sendall(("cat " + target + "\n").encode())
    response = recv_until_prompt(sock)
    if "alpha" not in response or "beta" not in response:
        print("[FAIL] 'ed append/print/write' did not save expected file content")
        print(f"       got: {response!r}")
        return False

    print("[PASS] 'ed append/print/write'                  → file content matched")
    return True


def run_example_tests(sock: socket.socket) -> tuple[int, int]:
    passed = 0
    failed = 0
    for runner in (
        run_hello_kernel_example,
        run_vfs_demo_example,
        run_async_tasks_example,
        run_primes_example,
        run_recv_file_example,
        run_send_file_example,
        run_tone_example,
    ):
        if runner(sock):
            passed += 1
        else:
            failed += 1
    return passed, failed


def run_simple_example(sock: socket.socket, expr: str, expected_markers: tuple[str, ...]) -> bool:
    sock.sendall(expr.encode())
    response = recv_until_prompt(sock)
    missing = [marker for marker in expected_markers if marker not in response]
    if not missing and ">>>" in response:
        print(f"[PASS] {expr.strip()!r:45s} -> found example markers")
        return True

    print(f"[FAIL] {expr.strip()!r:45s} -> missing {missing!r}")
    print(f"       got: {response!r}")
    return False


def run_hello_kernel_example(sock: socket.socket) -> bool:
    return run_simple_example(
        sock,
        "run('/examples/hello_kernel.py')\n",
        ("Hello, PythonOS!", "root entries:", "tasks:"),
    )


def run_vfs_demo_example(sock: socket.socket) -> bool:
    return run_simple_example(
        sock,
        "run('/examples/vfs_demo.py')\n",
        ("VFS demo wrote", "read back:", "PythonOS VFS demo"),
    )


def run_async_tasks_example(sock: socket.socket) -> bool:
    return run_simple_example(
        sock,
        "run('/examples/async_tasks.py')\n",
        ("async queue demo", "producer sent: 4", "consumer total: 10"),
    )


def run_primes_example(sock: socket.socket) -> bool:
    return run_simple_example(
        sock,
        "sh('/examples/primes.py 30')\n",
        ("Prime numbers up to 30", "found 10 primes"),
    )


def run_tone_example(sock: socket.socket) -> bool:
    expr = "run('/examples/tone.py')\n"
    sock.sendall(expr.encode())
    response = recv_until_prompt(sock)
    expected = (
        "Generated PythonOS tone buffer",
        "No HDA device is available",
    )
    for marker in expected:
        if marker in response and ">>>" in response:
            print(f"[PASS] {expr.strip()!r:45s} → found {marker!r}")
            return True

    print(f"[FAIL] {expr.strip()!r:45s} → expected a completed tone example status")
    print(f"       got: {response!r}")
    return False


def run_recv_file_example(sock: socket.socket) -> bool:
    payload = b"hello from recv_file example\n"
    target = "/tmp/example-recv.txt"
    expr = "sh('/examples/recv_file.py 7000 " + target + "')\n"

    sock.sendall(expr.encode())
    response = recv_until_prompt(sock, prompt=b"Saving to ")
    if "Receiving one file" not in response:
        print(f"[FAIL] {expr.strip()!r:45s} → recv_file did not start listening")
        print(f"       got: {response!r}")
        return False

    try:
        with socket.create_connection(("127.0.0.1", FILE_HOST_PORT), timeout=5) as data_sock:
            data_sock.sendall(payload)
    except OSError as e:
        print(f"[FAIL] {expr.strip()!r:45s} → host could not connect: {e}")
        return False

    response += recv_until_prompt(sock)
    expected = "saved " + str(len(payload)) + " bytes"
    if expected in response:
        print(f"[PASS] {expr.strip()!r:45s} → found {expected!r}")
        return True

    print(f"[FAIL] {expr.strip()!r:45s} → expected {expected!r}")
    print(f"       got: {response!r}")
    return False


def run_send_file_example(sock: socket.socket) -> bool:
    source = "/examples/README.txt"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(10)
    put_port = listener.getsockname()[1]
    expr = "sh('/examples/send_file.py 10.0.2.2 " + str(put_port) + " " + source + "')\n"

    received = b""
    try:
        sock.sendall(expr.encode())
        conn, _ = listener.accept()
        conn.settimeout(10)
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                received += chunk
        finally:
            conn.close()
    except OSError as e:
        print(f"[FAIL] {expr.strip()!r:45s} → host could not receive data: {e}")
        return False
    finally:
        listener.close()

    response = recv_until_prompt(sock)
    if b"PythonOS examples" not in received:
        print(f"[FAIL] {expr.strip()!r:45s} → received unexpected bytes")
        print(f"       got: {received!r}")
        return False
    if "sent " not in response or " bytes from " + source not in response:
        print(f"[FAIL] {expr.strip()!r:45s} → send_file did not report expected send")
        print(f"       got: {response!r}")
        return False

    print(f"[PASS] {expr.strip()!r:45s} → README bytes received")
    return True


def run_ftp_get_once(sock: socket.socket, target: str, payload: bytes) -> bool:
    sock.sendall(("ftp get " + target + "\n").encode())
    response = recv_until_prompt(
        sock,
        prompt=b"ftp: waiting for one incoming file stream",
    )
    if "ftp: waiting for one incoming file stream" not in response:
        print("[FAIL] 'ftp get' did not start listening")
        print(f"       got: {response!r}")
        return False

    try:
        with socket.create_connection(("127.0.0.1", FILE_HOST_PORT), timeout=5) as data_sock:
            data_sock.sendall(payload)
    except OSError as e:
        print(f"[FAIL] host could not connect to ftp get port {FILE_HOST_PORT}: {e}")
        return False

    response += recv_until_prompt(sock)
    expected = "ftp: saved " + str(len(payload)) + " bytes to " + target
    if expected not in response:
        print("[FAIL] 'ftp get' did not save expected bytes")
        print(f"       expected: {expected!r}")
        print(f"       got: {response!r}")
        return False

    return True


def run_ftp_put_once(sock: socket.socket, target: str, payload: bytes) -> bool:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(10)
    put_port = listener.getsockname()[1]

    received = b""
    try:
        sock.sendall(("ftp put " + target + " 10.0.2.2 " + str(put_port) + "\n").encode())
        conn, _ = listener.accept()
        conn.settimeout(10)
        try:
            while len(received) < len(payload):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                received += chunk
        finally:
            conn.close()
    except OSError as e:
        print(f"[FAIL] host could not receive ftp put data: {e}")
        return False
    finally:
        listener.close()

    response = recv_until_prompt(sock)
    if received != payload:
        print("[FAIL] 'ftp put' returned different bytes")
        print(f"       expected: {payload!r}")
        print(f"       got: {received!r}")
        return False
    if "ftp: sent " + str(len(payload)) + " bytes from " + target not in response:
        print("[FAIL] 'ftp put' did not report expected send")
        print(f"       got: {response!r}")
        return False

    return True


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
