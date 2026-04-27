# PythonOS build system
#
# Requires cross-compilation toolchain + NASM + GRUB + xorriso.
# On macOS, use the Docker target:
#   make docker-build && make docker-iso
#
# On Linux with the toolchain installed:
#   make iso

ARCH       := x86_64
TARGET     := $(ARCH)-elf

# Prefer the bare-metal cross-compiler (x86_64-elf-*); fall back to the
# Linux-hosted equivalent (x86_64-linux-gnu-*) when running on x86_64 Linux
# without the Docker toolchain aliases installed.
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

AS         := nasm

# CPython source dir — populated by: make cpython-build
CPYTHON    := deps/cpython
PYTHON_INC := $(CPYTHON)/Include
PYTHON_LIB := $(CPYTHON)/libpython3.13.a

# ── CFLAGS: two sets ──────────────────────────────────────────────────────────
#
# BOOT_CFLAGS — for src/boot/*.c (runs in interrupt context or before Python).
#   No SSE/MMX/x87: the FPU is not yet initialized when these run, and ISR
#   handlers must not use SSE between FXSAVE and FXRSTOR.
#
# KERN_CFLAGS — for src/libc/*.c and src/hal/hal.c (runs in task context with
#   full FPU state saved by isr_stubs.asm). SSE2 is the default for x86-64.

COMMON_CFLAGS := -std=c11 -O2 -ffreestanding -fno-stack-protector -fno-pie \
                 -mno-red-zone -Wall -Wextra \
                 -I src/libc/include \
                 -I $(PYTHON_INC) -I $(CPYTHON)

BOOT_CFLAGS := $(COMMON_CFLAGS) -mno-sse -mno-sse2 -mno-mmx -mno-80387
KERN_CFLAGS := $(COMMON_CFLAGS)

ASFLAGS    := -f elf64

# libgcc provides __udivti3, __muldf3 etc. for the cross-compiler
LIBGCC     := $(shell $(CC) -print-libgcc-file-name 2>/dev/null || echo "")

LDFLAGS    := -T linker.ld -nostdlib -z max-page-size=0x1000

BUILD      := build
ISO_DIR    := iso
ISO_OUT    := pythonos.iso

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

.PHONY: all iso clean docker-build docker-iso docker-qemu \
        qemu qemu-serial qemu-iso cpython cpython-build

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

# Individual stdlib files needed by the kernel (no socket/selectors/dis deps).
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
	@cp $(CPYTHON_LIB)/collections/abc.py      $(STDLIB_SHIM)/collections/
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

$(BUILD)/frozen_kernel.c: $(shell find kernel -name '*.py') \
                           $(shell find asyncio -name '*.py') \
                           $(shell find $(ENCODINGS_SRC) -name '*.py') \
                           $(STDLIB_SHIM)/.stamp
	@mkdir -p $(BUILD)
	python3.13 tools/freeze_kernel.py kernel asyncio $(ENCODINGS_SRC) \
	    $(STDLIB_SHIM) $(BUILD)/frozen_kernel.c

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

# Full device set: Q35 chipset, 512 MiB RAM, VirtIO-net, Intel HDA
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

# ── Docker (macOS host) ───────────────────────────────────────────────────────

DOCKER_IMG := pythonos-builder

docker-build:
	docker build --platform linux/amd64 --load -t $(DOCKER_IMG) -f tools/Dockerfile .

docker-iso: docker-build
	docker run --rm --platform linux/amd64 -v $(PWD):/work -w /work $(DOCKER_IMG) \
	  bash -c "make cpython-build && make iso"

docker-qemu: docker-iso
	qemu-system-$(ARCH) $(QEMU_BASE) \
	  -cdrom $(ISO_OUT) -boot d -nographic -serial mon:stdio

# ── CPython bare-metal build ──────────────────────────────────────────────────

cpython:
	./tools/setup_cpython.sh

cpython-build:
	./tools/setup_cpython.sh --build

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	rm -rf $(BUILD) $(ISO_OUT) $(ISO_DIR)/boot/pythonos.elf
