#!/usr/bin/env python3
"""
Boot smoke test for PythonOS arm64.

The arm64 kernel boots through the same kernel.boot() path as x86 but
runs an interactive shell on the PL011 serial line — it does not start
a TCP REPL because there is no PCI on QEMU virt and we have not wired
up VirtIO-MMIO networking yet. Rather than try to drive an interactive
serial REPL from a host script (which is its own nontrivial dance with
QEMU's terminal, raw mode, and timing), this smoke test boots the
kernel under QEMU, waits a fixed budget, then asserts that the serial
log contains every line we expect a healthy boot to emit.

This catches the things we actually want to catch:
  * Boot reached EL drop, MMU, GIC, timer, SMP init.
  * Python interpreter reached Py_Initialize done (so libpython is
    healthy on aarch64-elf).
  * kernel.boot() ran to completion and the async main loop took over.
  * The PL011 serial input handler is ready (so the kernel is happy to
    take user input on the serial line).

Failures land on the actual cause via the captured serial log printed
to stdout on test failure.

Usage:
    python3 tests/smoke_test_arm64.py [path/to/pythonos-arm64.elf]

Exit code: 0 = all markers found, 1 = one or more missing.
"""

import atexit
import os
import subprocess
import sys
import tempfile
import time

ELF = sys.argv[1] if len(sys.argv) > 1 else "pythonos-arm64.elf"
DISK = os.environ.get("PYTHONOS_ARM64_DISK", "disk-arm64.img")
SMP_CPUS = os.environ.get("PYTHONOS_ARM64_SMP_CPUS", "2")
BOOT_TIMEOUT = float(os.environ.get("PYTHONOS_ARM64_BOOT_TIMEOUT", "60"))

import platform


def _qemu_accel_for(target_arch: str) -> list:
    """HVF/KVM when guest matches host arch; generic CPU under TCG when
    cross-emulating. arm64 HVF on Apple Silicon requires GICv3, which our
    kernel doesn't implement, so arm64 stays on TCG until pythonos-h7g
    lands. Mirrors the GNUMakefile policy."""
    host_machine = platform.machine().lower()
    host_arch = "arm64" if host_machine in ("arm64", "aarch64") else "x86_64"
    host_os = platform.system()
    if host_arch != target_arch:
        return ["-cpu", "qemu64" if target_arch == "x86_64" else "cortex-a57"]
    if target_arch == "arm64":
        # HVF requires GICv3; defer to TCG.
        return ["-cpu", "cortex-a57"]
    accel = "hvf" if host_os == "Darwin" else ("kvm" if host_os == "Linux" else None)
    if accel:
        return ["-cpu", "host", "-accel", accel]
    return ["-cpu", "qemu64"]


QEMU_CMD = [
    "qemu-system-aarch64",
    "-machine", "virt",
    *_qemu_accel_for("arm64"),
    "-m", "2G", "-smp", SMP_CPUS,
    "-no-reboot", "-no-shutdown", "-nographic",
    "-drive", f"if=none,file={DISK},format=raw,id=hd0",
    "-device", "virtio-blk-device,drive=hd0",
    "-kernel", ELF,
]

# Markers we expect to see in serial output on a healthy boot. Each entry
# is (label, substring); ordering is informational only.
REQUIRED_MARKERS = [
    ("boot: serial",        "[PythonOS/arm64] boot: serial OK"),
    ("boot: MMU enabled",   "[PythonOS/arm64] boot: MMU enabled"),
    ("boot: TLS",           "[PythonOS/arm64] boot: TLS initialized"),
    ("boot: VBAR",          "[PythonOS/arm64] boot: VBAR set"),
    ("boot: GIC",           "[PythonOS/arm64] boot: GIC initialized"),
    ("boot: timer",         "[PythonOS/arm64] boot: timer started"),
    ("boot: SMP init",      "[PythonOS/arm64] boot: SMP init complete, online="),
    ("boot: Python kernel", "[PythonOS/arm64] boot: starting Python kernel"),
    ("hal: AppendInittab",  "[hal] AppendInittab"),
    ("hal: Py_Initialize",  "[hal] Py_Initialize done"),
    ("hal: kernel imported","[hal] kernel imported"),
    ("kernel.boot: starting", "kernel.boot: starting"),
    ("kernel.boot: PMM",    "kernel.boot: PMM ready"),
    ("kernel.boot: VMM",    "kernel.boot: VMM ready"),
    ("kernel.boot: tmpfs",  "kernel.boot: tmpfs mounted"),
    ("kernel.boot: main loop", "kernel.boot: entering main loop"),
    ("kernel: PL011 ready", "kernel: PL011 serial input ready"),
]


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

    cmd = QEMU_CMD + ["-serial", f"file:{serial_log.name}"]

    print(f"[smoke-arm64] Starting QEMU with {ELF} (-smp {SMP_CPUS}) ...")
    print(f"[smoke-arm64] Serial log: {serial_log.name}")
    print(f"[smoke-arm64] Boot budget: {BOOT_TIMEOUT}s")

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)

    final_marker = REQUIRED_MARKERS[-1][1]
    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            with open(serial_log.name) as f:
                content = f.read()
            if final_marker in content:
                break
        except OSError:
            pass
        time.sleep(1.0)

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    try:
        with open(serial_log.name) as f:
            content = f.read()
    except OSError:
        content = ""

    passed = 0
    failed = 0
    for label, substr in REQUIRED_MARKERS:
        if substr in content:
            print(f"[PASS] {label:30s} -> found {substr!r}")
            passed += 1
        else:
            print(f"[FAIL] {label:30s} -> missing {substr!r}")
            failed += 1

    print(f"\n[smoke-arm64] {passed} passed, {failed} failed")
    if failed:
        _print_serial(serial_log.name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
