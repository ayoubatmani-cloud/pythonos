# PythonOS build system
#
# Two build paths:
#
#   Docker path (macOS or any Linux — recommended for first-time setup):
#     make docker-build       # build cross-compilation image (once)
#     make docker-iso         # build everything inside Docker → pythonos.iso
#     make qemu-iso           # boot in QEMU
#
#   Native path (x86_64 Linux only):
#     make deps               # install host build tools (requires sudo)
#     make cpython-build      # cross-compile libpython3.14.a + freeze kernel
#                             #   (always runs in Docker; python3.14 required there)
#     make iso                # compile + link + create ISO (no Python needed)
#     make qemu-iso           # boot in QEMU
#
# make cpython-build always uses Docker because:
#   1. Cross-compiling libpython3.14.a requires a patched freestanding toolchain.
#   2. Freezing kernel modules requires python3.14 exactly — bytecode is
#      version-specific and must match the libpython being linked.

ARCH       := x86_64
TARGET     := $(ARCH)-elf

# Prefer the bare-metal cross-compiler (Docker alias); fall back to the
# Linux-hosted equivalent when running natively after 'make deps'.
ifneq ($(shell which $(TARGET)-gcc 2>/dev/null),)
  CC := $(TARGET)-gcc
  LD := $(TARGET)-ld
else ifneq ($(shell which $(ARCH)-linux-gnu-gcc 2>/dev/null),)
  CC := $(ARCH)-linux-gnu-gcc
  LD := $(ARCH)-linux-gnu-ld
else
  CC := gcc
  LD := ld
endif

AS := nasm

# CPython artifacts — populated by: make cpython-build
CPYTHON    := deps/cpython
PYTHON_INC := $(CPYTHON)/Include
PYTHON_LIB := $(CPYTHON)/libpython3.14.a

# ── CFLAGS: two sets ──────────────────────────────────────────────────────────
#
# BOOT_CFLAGS — src/boot/*.c: runs before FPU init, must avoid SSE/x87.
# KERN_CFLAGS — src/libc/*.c, src/hal/hal.c: full FPU state saved by ISR stubs.

COMMON_CFLAGS := -std=c11 -O2 -ffreestanding -fno-stack-protector -fno-pie \
                 -mno-red-zone -Wall -Wextra \
                 -I src/libc/include \
                 -I $(PYTHON_INC) -I $(CPYTHON)

BOOT_CFLAGS := $(COMMON_CFLAGS) -mno-sse -mno-sse2 -mno-mmx -mno-80387
KERN_CFLAGS := $(COMMON_CFLAGS)

ASFLAGS := -f elf64

# libgcc provides __udivti3, __muldf3 etc.
LIBGCC := $(shell $(CC) -print-libgcc-file-name 2>/dev/null || echo "")

LDFLAGS := -T linker.ld -nostdlib -z max-page-size=0x1000

BUILD   := build
ISO_DIR := iso
ISO_OUT := pythonos.iso

# ── Source files ──────────────────────────────────────────────────────────────

BOOT_ASM  := src/boot/boot.asm src/boot/isr_stubs.asm
BOOT_C    := src/boot/gdt.c src/boot/idt.c src/boot/main.c \
             src/boot/pit.c src/boot/fb.c
HAL_C     := src/hal/hal.c
LIBC_C    := src/libc/malloc.c  src/libc/string.c  src/libc/stdio.c \
             src/libc/time.c    src/libc/syscalls.c src/libc/math.c  \
             src/libc/pthread.c

BOOT_OBJS := $(patsubst src/%.asm,$(BUILD)/%.asm.o,$(BOOT_ASM))
BOOT_OBJS += $(patsubst src/%.c,$(BUILD)/%.c.o,$(BOOT_C))
HAL_OBJS  := $(patsubst src/%.c,$(BUILD)/%.c.o,$(HAL_C))
LIBC_OBJS := $(patsubst src/%.c,$(BUILD)/%.c.o,$(LIBC_C))

KERNEL_ELF := $(BUILD)/pythonos.elf

# ── Rules ─────────────────────────────────────────────────────────────────────

.PHONY: all iso clean deps \
        docker-build docker-iso docker-qemu \
        qemu qemu-serial qemu-iso qemu-debug \
        cpython cpython-build _freeze

all: $(KERNEL_ELF)

# ── Assembly ──────────────────────────────────────────────────────────────────

$(BUILD)/%.asm.o: src/%.asm
	@mkdir -p $(dir $@)
	$(AS) $(ASFLAGS) $< -o $@

# ── Boot C (no SSE) ───────────────────────────────────────────────────────────

$(BUILD)/boot/%.c.o: src/boot/%.c
	@mkdir -p $(dir $@)
	$(CC) $(BOOT_CFLAGS) -c $< -o $@

# ── Kernel C (SSE2 ok) ────────────────────────────────────────────────────────

$(BUILD)/hal/%.c.o: src/hal/%.c
	@mkdir -p $(dir $@)
	$(CC) $(KERN_CFLAGS) -c $< -o $@

$(BUILD)/libc/%.c.o: src/libc/%.c
	@mkdir -p $(dir $@)
	$(CC) $(KERN_CFLAGS) -c $< -o $@

# ── Frozen kernel modules ─────────────────────────────────────────────────────

ENCODINGS_SRC := deps/cpython-src/Lib/encodings
CPYTHON_LIB   := deps/cpython-src/Lib
STDLIB_SHIM   := $(BUILD)/stdlib_shim

STDLIB_REAL_FILES := \
	enum.py typing.py operator.py types.py \
	reprlib.py keyword.py copy.py weakref.py _weakrefset.py contextlib.py \
	warnings.py copyreg.py struct.py codeop.py

$(STDLIB_SHIM)/.stamp: $(CPYTHON_LIB)/enum.py $(CPYTHON_LIB)/struct.py $(CPYTHON_LIB)/codeop.py \
                        tools/stdlib_stubs/inspect.py \
                        tools/stdlib_stubs/pathlib.py \
                        tools/stdlib_stubs/functools.py \
                        tools/stdlib_stubs/dataclasses.py \
                        tools/stdlib_stubs/os.py \
                        tools/stdlib_stubs/ctypes/__init__.py \
                        tools/stdlib_stubs/random.py \
                        tools/stdlib_stubs/traceback.py \
                        tools/stdlib_stubs/linecache.py
	@mkdir -p $(STDLIB_SHIM)/re $(STDLIB_SHIM)/collections $(STDLIB_SHIM)/ctypes
	@$(foreach f,$(STDLIB_REAL_FILES),cp $(CPYTHON_LIB)/$(f) $(STDLIB_SHIM)/$(f);)
	@cp $(CPYTHON_LIB)/re/__init__.py  $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/re/_compiler.py $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/re/_parser.py   $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/re/_constants.py $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/re/_casefix.py  $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/collections/__init__.py $(STDLIB_SHIM)/collections/
	@cp $(CPYTHON_LIB)/_collections_abc.py    $(STDLIB_SHIM)/collections/abc.py
	@cp tools/stdlib_stubs/inspect.py    $(STDLIB_SHIM)/inspect.py
	@cp tools/stdlib_stubs/pathlib.py    $(STDLIB_SHIM)/pathlib.py
	@cp tools/stdlib_stubs/functools.py  $(STDLIB_SHIM)/functools.py
	@cp tools/stdlib_stubs/dataclasses.py $(STDLIB_SHIM)/dataclasses.py
	@cp tools/stdlib_stubs/os.py         $(STDLIB_SHIM)/os.py
	@cp tools/stdlib_stubs/ctypes/__init__.py $(STDLIB_SHIM)/ctypes/__init__.py
	@cp tools/stdlib_stubs/random.py         $(STDLIB_SHIM)/random.py
	@cp tools/stdlib_stubs/traceback.py      $(STDLIB_SHIM)/traceback.py
	@cp tools/stdlib_stubs/linecache.py      $(STDLIB_SHIM)/linecache.py
	@touch $@

# _freeze — runs python3.14 freeze_kernel.py.
# Called inside Docker by cpython-build and docker-iso (python3.14 guaranteed
# there). On native Linux, only reached if python3.14 is already present;
# otherwise cpython-build pre-generates the file so this rule is skipped.
_freeze: $(STDLIB_SHIM)/.stamp
	@mkdir -p $(BUILD)
	python3 tools/freeze_kernel.py kernel asyncio $(ENCODINGS_SRC) \
	    $(STDLIB_SHIM) $(BUILD)/frozen_kernel.c

# frozen_kernel.c is generated by 'make cpython-build' (inside Docker).
# On a native Linux build after cpython-build, the file already exists and
# this rule is a no-op (make sees the targets are up to date).
# If python3.14 happens to be available natively it is used directly.
$(BUILD)/frozen_kernel.c: $(shell find kernel asyncio -name '*.py' 2>/dev/null) \
                           $(STDLIB_SHIM)/.stamp
	@mkdir -p $(BUILD)
	@if python3 --version >/dev/null 2>&1; then \
	    python3 tools/freeze_kernel.py kernel asyncio $(ENCODINGS_SRC) \
	        $(STDLIB_SHIM) $(BUILD)/frozen_kernel.c; \
	elif [ -f $(BUILD)/frozen_kernel.c ]; then \
	    echo "==> frozen_kernel.c already built (python3.14 not found — using cached)"; \
	    touch $(BUILD)/frozen_kernel.c; \
	else \
	    echo ""; \
	    echo "ERROR: python3.14 not found and no pre-built frozen_kernel.c."; \
	    echo "Run 'make cpython-build' first — it generates frozen_kernel.c inside Docker."; \
	    echo ""; \
	    exit 1; \
	fi

$(BUILD)/frozen_kernel.o: $(BUILD)/frozen_kernel.c
	@mkdir -p $(BUILD)
	$(CC) $(KERN_CFLAGS) -c $< -o $@

# ── Final link ────────────────────────────────────────────────────────────────

$(KERNEL_ELF): $(BOOT_OBJS) $(HAL_OBJS) $(LIBC_OBJS) \
               $(BUILD)/frozen_kernel.o $(PYTHON_LIB)
	@mkdir -p $(BUILD)
	$(LD) $(LDFLAGS) -o $@ $^ $(LIBGCC)

# ── ISO ───────────────────────────────────────────────────────────────────────

iso: $(KERNEL_ELF)
	cp $(KERNEL_ELF) $(ISO_DIR)/boot/pythonos.elf
	grub-mkrescue -o $(ISO_OUT) $(ISO_DIR)
	@echo "ISO ready: $(ISO_OUT)"

# ── QEMU ─────────────────────────────────────────────────────────────────────

QEMU_BASE := -machine q35 -cpu qemu64 -m 512M \
             -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
             -device intel-hda -device hda-duplex \
             -no-reboot -no-shutdown

qemu: $(KERNEL_ELF)
	qemu-system-$(ARCH) $(QEMU_BASE) \
	  -kernel $(KERNEL_ELF) -display gtk

qemu-serial: $(KERNEL_ELF)
	qemu-system-$(ARCH) $(QEMU_BASE) \
	  -kernel $(KERNEL_ELF) -nographic -serial mon:stdio

qemu-iso: $(ISO_OUT)
	qemu-system-$(ARCH) $(QEMU_BASE) \
	  -cdrom $(ISO_OUT) -boot d -nographic -serial mon:stdio

qemu-debug: $(KERNEL_ELF)
	qemu-system-$(ARCH) $(QEMU_BASE) \
	  -kernel $(KERNEL_ELF) -nographic -serial mon:stdio \
	  -s -S &
	$(TARGET)-gdb $(KERNEL_ELF) \
	  -ex "target remote :1234" \
	  -ex "set arch i386:x86-64" \
	  -ex "break kernel_main" \
	  -ex "continue"

# ── Docker ────────────────────────────────────────────────────────────────────

DOCKER_IMG := pythonos-builder

docker-build:
	docker build --platform linux/amd64 --load -t $(DOCKER_IMG) -f tools/Dockerfile .

# cpython-build: cross-compile libpython3.14.a AND generate frozen_kernel.c.
# Runs entirely inside Docker (python3.14 + cross-toolchain guaranteed there).
# After this target, 'make iso' can run natively without needing python3.14.
cpython-build: docker-build
	docker run --rm --platform linux/amd64 -v $(PWD):/work -w /work $(DOCKER_IMG) \
	  bash -c "./tools/setup_cpython.sh --build && make _freeze"

# docker-iso: build everything inside Docker. Use this on macOS or when you
# prefer not to install native build tools.
docker-iso: docker-build
	docker run --rm --platform linux/amd64 -v $(PWD):/work -w /work $(DOCKER_IMG) \
	  bash -c "./tools/setup_cpython.sh --build && make _freeze && make iso"

docker-qemu: docker-iso
	qemu-system-$(ARCH) $(QEMU_BASE) \
	  -cdrom $(ISO_OUT) -boot d -nographic -serial mon:stdio

# Legacy alias kept for compatibility
cpython:
	./tools/setup_cpython.sh

# ── deps — install native host build tools ────────────────────────────────────
#
# Installs the tools needed for 'make iso' on Linux.
# Does NOT install python3.14 or Docker — cpython-build handles those.
# On macOS, native build is not supported; use 'make docker-iso' instead.

deps:
	@if command -v apt-get >/dev/null 2>&1; then \
	    echo "==> Installing build dependencies via apt-get..."; \
	    sudo apt-get update -qq && sudo apt-get install -y \
	        nasm \
	        gcc binutils \
	        grub-pc-bin grub-common \
	        xorriso mtools \
	        qemu-system-x86; \
	    echo ""; \
	    echo "==> Host tools installed."; \
	    echo "Next steps:"; \
	    echo "  make cpython-build   # cross-compile libpython + freeze kernel (Docker)"; \
	    echo "  make iso             # compile + link + create ISO (native)"; \
	    echo "  make qemu-iso        # boot in QEMU"; \
	elif command -v brew >/dev/null 2>&1; then \
	    echo "macOS native build is not supported (requires x86 cross-toolchain)."; \
	    echo "Use Docker instead:"; \
	    echo "  make docker-build && make docker-iso"; \
	    echo ""; \
	    echo "Installing QEMU for running the ISO:"; \
	    brew install qemu; \
	else \
	    echo "Unsupported platform. Install these packages manually:"; \
	    echo "  nasm gcc binutils grub-pc-bin grub-common xorriso mtools qemu-system-x86"; \
	fi

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	rm -rf $(BUILD) $(ISO_OUT) $(ISO_DIR)/boot/pythonos.elf
