#!/usr/bin/env bash
# setup_cpython.sh — Download, patch, and configure CPython for bare-metal PythonOS.
#
# Run inside the Docker build environment (Ubuntu 24.04) or on any Linux host
# with the cross-compiler toolchain installed.
#
# Usage:
#   ./tools/setup_cpython.sh           # downloads CPython 3.13, patches, configures
#   ./tools/setup_cpython.sh --build   # also compiles libpython3.13.a
#
# Output: deps/cpython/ — configured CPython source tree
#         deps/cpython/libpython3.13.a — static library (with --build)
#
# Two-phase build strategy:
#   Phase 1 — ./configure runs with the HOST compiler (gcc) so that all
#              feature probes can compile, link, and execute on the build machine.
#              ac_cv_* cache variables pre-answer the probes that would wrongly
#              detect POSIX features we don't have.
#   Phase 2 — make libpython3.13.a is driven with the CROSS compiler
#              (x86_64-elf-gcc = x86_64-linux-gnu-gcc in Docker) plus our
#              bare-metal CFLAGS. Our pyconfig.h (installed after configure)
#              overrides everything configure detected, so the resulting .o
#              files only depend on symbols we actually provide.

set -euo pipefail

CPYTHON_VERSION="3.13.0"
CPYTHON_URL="https://www.python.org/ftp/python/${CPYTHON_VERSION}/Python-${CPYTHON_VERSION}.tar.xz"
CPYTHON_SHA256="086de5882e3cb310d4dca48457522e2e48018ecd43da9cdf827f6a0759efb07d"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPS_DIR="$REPO_ROOT/deps"
CPYTHON_SRC="$DEPS_DIR/cpython-src"
CROSS_PREFIX="x86_64-elf"
CC="${CROSS_PREFIX}-gcc"
AR="${CROSS_PREFIX}-ar"
RANLIB="${CROSS_PREFIX}-ranlib"

# Bare-metal CFLAGS for the actual library build (Phase 2).
# NOT passed to configure — they would break configure's linker probes.
#
# NOTE: do NOT pass -mno-sse/-mno-sse2 here. Those flags are only for the
#   kernel boot/ISR code (see BOOT_CFLAGS in Makefile). CPython must be
#   able to generate SSE2 code since it runs with FPU state fully saved.
# NOTE: do NOT define -D_GNU_SOURCE or -D_POSIX_C_SOURCE. Those feature-test
#   macros cause system headers to transitively include bits/pthreadtypes.h
#   which defines real Linux pthread struct layouts that conflict with our stubs.
TARGET_CFLAGS="-std=c11 -O2 -ffreestanding -fno-stack-protector -fno-pie \
  -mno-red-zone \
  -I${REPO_ROOT}/src/libc/include \
  -I${REPO_ROOT}/deps/cpython \
  -DPy_BUILD_CORE=1 \
  -DNDEBUG=1 \
  -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0"

echo "==> PythonOS CPython bare-metal setup v${CPYTHON_VERSION}"

# ── 1. Download ──────────────────────────────────────────────────────────────
mkdir -p "$DEPS_DIR"
TARBALL="$DEPS_DIR/Python-${CPYTHON_VERSION}.tar.xz"
if [ ! -f "$TARBALL" ]; then
    echo "==> Downloading CPython ${CPYTHON_VERSION}..."
    curl -L "$CPYTHON_URL" -o "$TARBALL"
fi

echo "==> Verifying checksum..."
echo "${CPYTHON_SHA256}  $TARBALL" | sha256sum -c -

# ── 2. Extract ───────────────────────────────────────────────────────────────
if [ ! -d "$CPYTHON_SRC" ]; then
    echo "==> Extracting..."
    tar -xf "$TARBALL" -C "$DEPS_DIR"
    mv "$DEPS_DIR/Python-${CPYTHON_VERSION}" "$CPYTHON_SRC"
fi

cd "$CPYTHON_SRC"

# ── 3. Apply patches ─────────────────────────────────────────────────────────
echo "==> Applying bare-metal patches..."

# Patch 1: Remove #include <sys/select.h> from timemodule.c — we don't have it
if ! grep -q "PythonOS_patched" Modules/timemodule.c; then
    sed -i 's/#ifdef HAVE_SELECT/#if 0 \/\* PythonOS_patched \*\//g' Modules/timemodule.c
    echo "  patched: Modules/timemodule.c"
fi

# Patch 2: signalmodule.c — disable sigaltstack (needs sys/types.h)
if ! grep -q "PythonOS_patched" Modules/signalmodule.c; then
    sed -i 's/#ifdef HAVE_SIGALTSTACK/#if 0 \/\* PythonOS_patched \*\//g' Modules/signalmodule.c
    echo "  patched: Modules/signalmodule.c"
fi

# Patch 3: Python/fileutils.c — disable the fd cloexec loop (no fork)
if ! grep -q "PythonOS_patched" Python/fileutils.c; then
    sed -i 's/res = fcntl(fd, F_SETFD, new_flags);/res = 0; \/\/ PythonOS_patched: skipped fcntl/g' Python/fileutils.c
    echo "  patched: Python/fileutils.c"
fi

# Patch 4: pycore_pyhash.h uses dev_t/ino_t without including sys/types.h
if ! grep -q "PythonOS_patched" Include/internal/pycore_pyhash.h; then
    sed -i 's/#ifndef Py_BUILD_CORE/#include <sys\/types.h> \/\* PythonOS_patched *\/ \n#ifndef Py_BUILD_CORE/' \
        Include/internal/pycore_pyhash.h
    echo "  patched: Include/internal/pycore_pyhash.h"
fi

# ── 4. Configure with HOST compiler (Phase 1) ─────────────────────────────────
# We deliberately do NOT pass CC/CFLAGS/LDFLAGS here. configure must be able
# to compile, link, and run test programs on the build host. The bare-metal
# flags (-ffreestanding, -nostdlib) would prevent any linker probes from
# succeeding, confusing configure into thinking the compiler is broken.
#
# We override the probes that matter via ac_cv_* cache variables, and we
# install our own pyconfig.h AFTER configure (which regenerates it from
# pyconfig.h.in during the configure run).

echo "==> Phase 1: Configuring CPython with host compiler..."
./configure \
    --without-pydebug \
    --disable-shared \
    --without-ensurepip \
    --without-readline \
    --disable-ipv6 \
    --without-dtrace \
    --without-c-locale-coercion \
    --with-computed-gotos \
    ac_cv_file__dev_ptmx=no \
    ac_cv_file__dev_null=no \
    ac_cv_header_netinet_in_h=no \
    ac_cv_header_sys_socket_h=no \
    ac_cv_header_sys_select_h=no \
    ac_cv_header_fcntl_h=no \
    ac_cv_header_unistd_h=no \
    ac_cv_func_fork=no \
    ac_cv_func_execv=no \
    ac_cv_func_getpid=yes \
    ac_cv_func_mmap_fixed_mapped=yes \
    2>&1 | tee "$DEPS_DIR/configure.log"

echo "==> Configuration complete. Log: $DEPS_DIR/configure.log"

# ── 5. Install our pyconfig.h and Modules/Setup.local ────────────────────────
# These MUST come after configure, which regenerates pyconfig.h from
# pyconfig.h.in. Our version overrides the host-detected values with the
# bare-metal subset our libc actually provides.
echo "==> Installing bare-metal pyconfig.h..."
cp "$REPO_ROOT/deps/pyconfig.h" "$CPYTHON_SRC/pyconfig.h"

echo "==> Installing Modules/Setup.local..."
cp "$REPO_ROOT/deps/Modules.Setup.local" "$CPYTHON_SRC/Modules/Setup.local"

# ── 5b. Post-configure Makefile patches ──────────────────────────────────────
# In CPython 3.13, some modules moved out of Modules/ but the configure-generated
# Makefile still lists stale entries. Patch them here:
#   - _warnings: code is in Python/_warnings.c (already in Python/*.o) — remove
#   - _string: code is in Objects/unicodeobject.c — remove
#   - _csvmodule.c renamed to _csv.c — fix object and rule
#   - sha256module.c / sha512module.c → sha2module.c (needs HACL) — skip for now
#   - hal path: ../../src/hal → ../../../src/hal (one more level up from Modules/)
echo "==> Patching configure-generated Makefile..."
# Redirect _freeze_module and _bootstrap_python to python3.13 — both binaries
# link libpython with -fno-pie which fails Ubuntu 24.04's PIE-only linker.
# python3.13 MUST be used here (not python3/python3.12): the frozen module
# bytecode must be compiled with the same Python version as the interpreter
# (RESUME opcode = 149 in 3.13; Python 3.12 has RESUME = 151, which causes
# the bare-metal interpreter to misidentify RESUME as BINARY_OP_ADD_INT).
sed -i \
    -e 's|^PYTHON_FOR_FREEZE=.*$|PYTHON_FOR_FREEZE=python3.13|' \
    -e 's|^FREEZE_MODULE_BOOTSTRAP=.*$|FREEZE_MODULE_BOOTSTRAP=python3.13 ./Programs/_freeze_module.py|' \
    -e 's|^FREEZE_MODULE_BOOTSTRAP_DEPS=.*$|FREEZE_MODULE_BOOTSTRAP_DEPS=Programs/_freeze_module.py|' \
    -e 's|^FREEZE_MODULE_DEPS=.*$|FREEZE_MODULE_DEPS=$(srcdir)/Programs/_freeze_module.py|' \
    "$CPYTHON_SRC/Makefile"
# Remove stale/excluded module objects
sed -i \
    -e 's/ Modules\/_warnings\.o / /g' \
    -e 's/ Modules\/_string\.o / /g' \
    -e 's/ Modules\/sha256module\.o  Modules\/sha512module\.o / /g' \
    -e 's/ Modules\/_csvmodule\.o / Modules\/_csv.o /g' \
    -e 's|Modules/\.\./\.\./src/hal/|Modules/../../../src/hal/|g' \
    -e 's/ Modules\/posixmodule\.o / /g' \
    -e 's| Modules/_decimal/_decimal\.o | |g' \
    -e 's/ Modules\/sha1module\.o / /g' \
    -e 's/ Modules\/md5module\.o / /g' \
    -e 's/ Modules\/pwdmodule\.o / /g' \
    "$CPYTHON_SRC/Makefile"
# Remove binascii's zlib dependency: clear USE_ZLIB_CRC32 flag and -lz linker flag
# sha1/md5 use HACL library which we don't provide; remove their CFLAGS entirely
sed -i \
    -e 's|^MODULE_BINASCII_CFLAGS=.*$|MODULE_BINASCII_CFLAGS=|' \
    -e 's|^MODULE_BINASCII_LDFLAGS=.*$|MODULE_BINASCII_LDFLAGS=|' \
    "$CPYTHON_SRC/Makefile"
# Fix the _csv.o build rule (source file renamed from _csvmodule.c to _csv.c)
sed -i \
    -e 's|Modules/_csvmodule\.o: \$(srcdir)/Modules/_csvmodule\.c|Modules/_csv.o: $(srcdir)/Modules/_csv.c|g' \
    -e 's|-c \$(srcdir)/Modules/_csvmodule\.c -o Modules/_csvmodule\.o|-c $(srcdir)/Modules/_csv.c -o Modules/_csv.o|g' \
    "$CPYTHON_SRC/Makefile"
# Neuter PIE-incompatible binary targets: _freeze_module and _bootstrap_python.
# Both link libpython with -fno-pie which fails Ubuntu 24.04's PIE-only linker.
# Replace their link recipes with no-ops; frozen modules use python3 script.
python3 - "$CPYTHON_SRC/Makefile" <<'PYEOF'
import sys, re
path = sys.argv[1]
text = open(path).read()
# Neuter Programs/_freeze_module link rule
text = re.sub(
    r'Programs/_freeze_module: Programs/_freeze_module\.o[^\n]*\n'
    r'\t\$\(LINKCC\)[^\n]*\n',
    'Programs/_freeze_module: Programs/_freeze_module.py\n'
    '\t@echo "PythonOS: skipping _freeze_module binary (using python3 script)"\n',
    text
)
# Neuter _bootstrap_python link rule (multi-line: two recipe lines)
text = re.sub(
    r'_bootstrap_python: [^\n]*\n'
    r'\t\$\(LINKCC\)[^\n]*\\\n'
    r'\t\t[^\n]*\n',
    '_bootstrap_python: Programs/_freeze_module.py\n'
    '\t@echo "PythonOS: skipping _bootstrap_python binary (using system python3)"\n'
    '\t@touch _bootstrap_python\n',
    text
)
open(path, 'w').write(text)
PYEOF
# Regenerate Modules/config.c from our custom Setup.local so that make
# does not try to regenerate it (and lose our Makefile patches).
# We discard the Makefile fragment output and only keep config.c.
echo "==> Regenerating Modules/config.c from our Setup.local..."
"$CPYTHON_SRC/Misc/makesetup" \
    -c "$CPYTHON_SRC/Modules/config.c.in" \
    -s "$CPYTHON_SRC/Modules" \
    "$CPYTHON_SRC/Modules/Setup.local" \
    "$CPYTHON_SRC/Modules/Setup.stdlib" \
    "$CPYTHON_SRC/Modules/Setup.bootstrap" \
    "$CPYTHON_SRC/Modules/Setup" \
    > /dev/null 2>&1 || true

# Touch Makefile AND config.c AFTER patching so make does not re-generate
# them when it sees Setup.local is newer (autoconf self-regen rule).
touch "$CPYTHON_SRC/Makefile"
touch "$CPYTHON_SRC/Modules/config.c"

# ── 5c. Pre-generate frozen module headers ────────────────────────────────────
# Programs/_freeze_module is a HOST tool that must compile and run on the build
# host. Since we cross-compile with -ffreestanding/-fno-pie, the binary can't
# be built normally. Instead, use the pure-Python implementation with python3.13.
#
# CRITICAL: python3.13 must be used (not python3/python3.12). The frozen
# bytecode must use the same opcode numbering as the interpreter:
#   CPython 3.13: RESUME = 149    Python 3.12: RESUME = 151 (WRONG!)
# Using python3.12 produces frozen modules with opcode 151 at instruction 0,
# which the 3.13 interpreter dispatches as BINARY_OP_ADD_INT, causing an
# immediate page fault before any Python code can run.
FREEZE_PY=$(command -v python3.13 2>/dev/null || command -v python3 2>/dev/null)
FREEZE_PY_VER=$("$FREEZE_PY" -c "import sys; print(sys.version_info[:2])" 2>/dev/null)
if [[ "$FREEZE_PY_VER" != "(3, 13)" ]]; then
    echo "ERROR: python3.13 is required to generate frozen modules but found $FREEZE_PY ($FREEZE_PY_VER)"
    echo "       Install python3.13 and retry."
    exit 1
fi
echo "==> Pre-generating frozen module headers with $FREEZE_PY ($FREEZE_PY_VER)..."
mkdir -p Python/frozen_modules
# Always regenerate all frozen module headers — tarball timestamps cannot be
# trusted and using the wrong Python version silently corrupts the bytecode.
grep -A1 'frozen_modules/.*\.h:' Makefile \
    | grep 'FREEZE_MODULE' \
    | sed 's/.*BOOTSTRAP) //' \
    | sed 's/.*FREEZE_MODULE) //' \
    | sed "s|\$(srcdir)|.|g" \
    | while read -r modname srcpy outfile; do
        if [ -n "$modname" ] && [ -n "$outfile" ]; then
            echo "  freezing: $modname"
            "$FREEZE_PY" "$CPYTHON_SRC/Programs/_freeze_module.py" \
                "$modname" "$CPYTHON_SRC/$srcpy" "$CPYTHON_SRC/$outfile" \
                2>/dev/null || true
        fi
      done
# Touch all frozen headers to prevent make from trying to regenerate them
touch Python/frozen_modules/*.h 2>/dev/null || true

# ── 6. Optionally build (Phase 2) ─────────────────────────────────────────────
if [[ "${1:-}" == "--build" ]]; then
    echo "==> Phase 2: Building libpython3.13.a with cross-compiler..."
    echo "    CC=$CC"
    echo "    CFLAGS=$TARGET_CFLAGS"

    # Clean previous objects so CFLAGS changes (e.g. -U_FORTIFY_SOURCE) take
    # effect — make does not track compiler flag changes in its dependency graph.
    echo "==> Cleaning previous build artifacts..."
    find "$CPYTHON_SRC" -name '*.o' -delete 2>/dev/null || true
    rm -f "$CPYTHON_SRC/libpython3.13.a"

    make -j"$(nproc)" libpython3.13.a \
        CC="$CC" \
        AR="$AR" \
        RANLIB="$RANLIB" \
        CFLAGS="$TARGET_CFLAGS" \
        LDFLAGS="" \
        2>&1 | tee "$DEPS_DIR/build.log"

    # Copy outputs where the Makefile expects them
    mkdir -p "$DEPS_DIR/cpython/Include"
    cp libpython3.13.a "$DEPS_DIR/cpython/libpython3.13.a"
    cp -r Include/. "$DEPS_DIR/cpython/Include/"
    echo "==> Done. Library: $DEPS_DIR/cpython/libpython3.13.a"
else
    echo ""
    echo "Next: ./tools/setup_cpython.sh --build"
    echo "  or: cd $CPYTHON_SRC && make -j\$(nproc) libpython3.13.a CC=$CC CFLAGS=..."
fi

echo "==> CPython bare-metal setup complete."
