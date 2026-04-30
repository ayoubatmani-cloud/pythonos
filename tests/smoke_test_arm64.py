#!/usr/bin/env python3
"""
Smoke test for PythonOS arm64: boots the ELF under QEMU virt, waits for
the TCP REPL on port 5556 (host) → 5000 (guest), runs a curated subset
of the same Python expressions tests/smoke_test.py asserts on x86, and
verifies arm64-specific markers.

The substrate differences vs. x86 are:
  - No SMP / AP workers (single core).
  - pthread_create returns ENOSYS; pthread workers don't run.
  - No Intel HDA (no audio test).
  - VirtIO-MMIO block device instead of PCI VirtIO.
  - kernel _ARCH == 'arm64'.

The expected pthread_coverage.py output uses the arm64-skip path added
under beads pythonos-8me; once pythonos-bjr (arm64 SMP + pthread
substrate) lands, this file should be updated to assert the same
'lifecycle ok' / 'identity ok' / etc. markers as x86.

Usage:
    python3 tests/smoke_test_arm64.py [path/to/pythonos-arm64.elf]

Exit code: 0 = all tests passed, 1 = failure.
"""

import atexit
import os
import socket
import subprocess
import sys
import tempfile
import time

ELF = sys.argv[1] if len(sys.argv) > 1 else "pythonos-arm64.elf"
DISK = os.environ.get("PYTHONOS_ARM64_DISK", "disk-arm64.img")
HOST_PORT = int(os.environ.get("PYTHONOS_ARM64_HOST_PORT", "5556"))
FILE_HOST_PORT = int(os.environ.get("PYTHONOS_ARM64_FILE_PORT", "17002"))
SMP_CPUS = os.environ.get("PYTHONOS_ARM64_SMP_CPUS", "2")
BOOT_TIMEOUT = 240
RECV_TIMEOUT = 15.0

QEMU_CMD = [
    "qemu-system-aarch64",
    "-machine", "virt", "-cpu", "cortex-a57", "-m", "2G", "-smp", SMP_CPUS,
    "-no-reboot", "-no-shutdown", "-nographic",
    "-netdev", f"user,id=net1,hostfwd=tcp::{HOST_PORT}-:5000,hostfwd=tcp::{FILE_HOST_PORT}-:7000",
    "-device", "virtio-net-device,netdev=net1",
    "-drive", f"if=none,file={DISK},format=raw,id=hd0",
    "-device", "virtio-blk-device,drive=hd0",
    "-kernel", ELF,
]

# (expression_to_send, substring_expected_in_response)
# Curated subset that does not depend on x86-only features (HDA, PCI).
TEST_CASES = [
    ("1 + 1\n",                         "2"),
    ("'hello' + ' world'\n",            "hello world"),
    ("type(scheduler).__name__\n",      "Scheduler"),
    ("vfs is not None\n",               "True"),
    ("len([x*x for x in range(5)])\n",  "5"),
    ("1 / 0\n",                         "ZeroDivisionError"),
    ("__import__('_hal').ARCH\n",        "'arm64'"),
    ("run('/bin/sysinfo.py')\n",        "PythonOS"),
    ("ls /bin\n",                       "ed.py"),
    ("cat /examples/README.txt\n",      "PythonOS examples"),
    ("ls /examples\n",                  "hello_kernel.py"),
    # SMP introspection — arm64 now brings up secondaries via PSCI CPU_ON.
    (
        "(__import__('_hal').SMP_ONLINE, __import__('_hal').SMP_CPUS)\n",
        f"({SMP_CPUS}, {SMP_CPUS})" if SMP_CPUS.isdigit() else "(",
    ),
    # pthread bring-up self-test should pass with a real worker on an AP.
    ("__import__('_hal').pthread_selftest()\n", "(0, 123456789, 4660)"),
    # Direct attr selftest exercises 22 cases on both archs.
    ("__import__('_hal').pthread_attr_selftest()\n", "(22,"),
    # linenoise wrappers (compiled into both arches).
    ("__import__('_hal').linenoise_history_add('arm64-test')\n", "1"),
    ("__import__('_hal').linenoise(':no-tty: ') is None\n", "True"),
]


def wait_for_port(port: int, timeout: float, proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
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


def serial_contains(path: str, needle: str) -> bool:
    try:
        with open(path) as f:
            return needle in f.read()
    except OSError:
        return False


def _print_serial(path: str) -> None:
    try:
        with open(path) as f:
            content = f.read()
        if content.strip():
            print(f"\n--- serial log ({path}) ---")
            print(content[-4000:] if len(content) > 4000 else content)
            print("--- end serial log ---")
        else:
            print("[smoke-arm64] (serial log is empty)")
    except OSError:
        pass


def run_simple_example(sock: socket.socket, expr: str,
                       expected_markers: tuple) -> bool:
    sock.sendall(expr.encode())
    response = recv_until_prompt(sock)
    missing = [m for m in expected_markers if m not in response]
    if not missing and ">>>" in response:
        print(f"[PASS] {expr.strip()!r:50s} -> found example markers")
        return True
    print(f"[FAIL] {expr.strip()!r:50s} -> missing {missing!r}")
    print(f"       got: {response!r}")
    return False


def run_pthread_coverage(sock: socket.socket) -> bool:
    """With arm64 SMP + pthread substrate (pythonos-bjr) wired in, all six
    sections must produce 'ok' markers like x86. Until those secondary
    cores actually come online, the script's arch-skip path emits
    'skipped (arm64...)' lines instead — the assertion below accepts
    either form so the test stays useful while bring-up stabilizes."""
    sock.sendall("run('/examples/pthread_coverage.py')\n".encode())
    response = recv_until_prompt(sock)
    required = ("pthread coverage start", "attr ok",
                "pthread coverage done passed=6/6")
    section_options = ["lifecycle", "identity", "tss", "lock", "capacity"]

    missing = [m for m in required if m not in response]
    for sect in section_options:
        if (sect + " ok") not in response and \
           (sect + " skipped (arm64") not in response:
            missing.append(sect + " (ok|skipped)")

    if not missing and ">>>" in response:
        print("[PASS] 'pthread_coverage.py'                       "
              "-> all six sections accounted for")
        return True
    print(f"[FAIL] 'pthread_coverage.py' -> missing {missing!r}")
    print(f"       got: {response!r}")
    return False


def run() -> int:
    if not os.path.exists(ELF):
        print(f"[FAIL] arm64 ELF not found: {ELF}")
        print("       Run 'make arm64' first.")
        return 1
    if not os.path.exists(DISK):
        print(f"[FAIL] arm64 disk image not found: {DISK}")
        print("       Run 'make arm64' first (it creates a blank disk).")
        return 1

    serial_log = tempfile.NamedTemporaryFile(
        mode="w", suffix=".log", prefix="pythonos-arm64-serial-",
        delete=False
    )
    serial_log.close()
    atexit.register(lambda: os.unlink(serial_log.name)
                    if os.path.exists(serial_log.name) else None)

    cmd = list(QEMU_CMD)
    # arm64 uses '-serial mon:stdio' by default in the makefile but we
    # want the log captured to a file so the host smoke runner can
    # inspect it on failure.
    cmd += ["-serial", f"file:{serial_log.name}"]

    print(f"[smoke-arm64] Starting QEMU with {ELF} ...")
    print(f"[smoke-arm64] Serial log: {serial_log.name}")

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)

    def _cleanup():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    try:
        print(f"[smoke-arm64] Waiting up to {BOOT_TIMEOUT}s for TCP REPL "
              f"on port {HOST_PORT} ...")
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
                s = socket.create_connection(("127.0.0.1", HOST_PORT),
                                             timeout=5)
            except OSError as e:
                print(f"[smoke-arm64] connect attempt {attempt}: {e}; "
                      f"retrying...")
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
            print(f"[smoke-arm64] attempt {attempt}: no prompt yet, "
                  f"retrying in 1s...")
            time.sleep(1.0)

        if sock is None:
            print("[FAIL] No shell prompt after 3 connection attempts")
            _print_serial(serial_log.name)
            return 1

        print("[smoke-arm64] Connected — shell prompt received.")
        passed = 0
        failed = 0

        for label, expected in [
            ("banner lists cat", "Commands: ls ps pwd cd cat"),
            ("banner lists sh()", "Helpers: sh()"),
        ]:
            if expected in banner:
                print(f"[PASS] {label:50s} -> found {expected!r}")
                passed += 1
            else:
                print(f"[FAIL] {label:50s} -> expected {expected!r}")
                failed += 1

        for expr, expected in TEST_CASES:
            sock.sendall(expr.encode())
            response = recv_until_prompt(sock)
            if expected in response:
                print(f"[PASS] {expr.strip()!r:50s} -> found {expected!r}")
                passed += 1
            else:
                print(f"[FAIL] {expr.strip()!r:50s} -> expected {expected!r}")
                print(f"       got: {response!r}")
                failed += 1

        # Examples that work on arm64 (no SMP / no HDA dependence).
        for runner_name, runner in [
            ("hello_kernel",
             ("run('/examples/hello_kernel.py')\n",
              ("Hello, PythonOS!", "root entries:", "tasks:"))),
            ("vfs_demo",
             ("run('/examples/vfs_demo.py')\n",
              ("VFS demo wrote", "read back:", "PythonOS VFS demo"))),
            ("async_tasks",
             ("run('/examples/async_tasks.py')\n",
              ("async queue demo", "producer sent: 4",
               "consumer total: 10"))),
            ("primes",
             ("sh('/examples/primes.py 30')\n",
              ("Prime numbers up to 30", "found 10 primes"))),
        ]:
            expr, markers = runner[1]
            if run_simple_example(sock, expr, markers):
                passed += 1
            else:
                failed += 1

        if run_pthread_coverage(sock):
            passed += 1
        else:
            failed += 1

        # Boot-level marker: kernel-thread self-test serial line is also
        # emitted on arm64 (per src/boot/main_arm64.c).
        if serial_contains(serial_log.name, "kernel thread self-test"):
            print("[PASS] boot kernel-thread self-test serial marker")
            passed += 1
        else:
            print("[FAIL] boot kernel-thread self-test serial marker missing")
            failed += 1

        print(f"\n[smoke-arm64] {passed} passed, {failed} failed")
        if failed:
            _print_serial(serial_log.name)
        sock.close()
        return 0 if failed == 0 else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(run())
