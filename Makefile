# PythonOS build system — Docker-only
#
# All compilation happens inside Docker (cross-toolchain + python3.14 guaranteed).
# QEMU runs on the host to boot the resulting ISO.
#
# Quick start:
#   make          # build everything → pythonos.iso
#   make run      # build + boot in QEMU (serial console)
#   make stop     # kill running QEMU instance
#   make clean    # remove build artifacts

ARCH      := x86_64
ISO_OUT   := pythonos.iso
DOCKER_IMG := pythonos-builder

QEMU_FLAGS := -machine q35 -cpu qemu64 -m 512M \
              -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
              -device intel-hda -device hda-duplex \
              -no-reboot -no-shutdown \
              -cdrom $(ISO_OUT) -boot d -nographic -serial mon:stdio

# ── User-facing targets ───────────────────────────────────────────────────────

.PHONY: all run start stop restart test clean \
        docker-build _iso _freeze

all: $(ISO_OUT)

$(ISO_OUT): docker-build
	docker run --rm --platform linux/amd64 -v $(PWD):/work -w /work $(DOCKER_IMG) \
	  bash -c "./tools/setup_cpython.sh --build && make _freeze && make _iso"
	@echo "ISO ready: $(ISO_OUT)"

run: $(ISO_OUT)
	qemu-system-$(ARCH) $(QEMU_FLAGS)

start: run

stop:
	@pkill -f "qemu-system-$(ARCH).*$(ISO_OUT)" || echo "No QEMU instance running."

restart: stop start

test:
	@echo "No tests yet." && exit 0

clean:
	rm -rf build $(ISO_OUT) iso/boot/pythonos.elf

# ── Docker image ─────────────────────────────────────────────────────────────

docker-build:
	docker build --platform linux/amd64 --load -t $(DOCKER_IMG) -f tools/Dockerfile .

# ── Internal targets — called from inside Docker, not by users ────────────────

TARGET  := $(ARCH)-elf
CC      := $(TARGET)-gcc
LD      := $(TARGET)-ld
AS      := nasm

CPYTHON    := deps/cpython
PYTHON_INC := $(CPYTHON)/Include
PYTHON_LIB := $(CPYTHON)/libpython3.14.a

COMMON_CFLAGS := -std=c11 -O2 -ffreestanding -fno-stack-protector -fno-pie \
                 -mno-red-zone -Wall -Wextra \
                 -I src/libc/include \
                 -I $(PYTHON_INC) -I $(CPYTHON)

BOOT_CFLAGS := $(COMMON_CFLAGS) -mno-sse -mno-sse2 -mno-mmx -mno-80387
KERN_CFLAGS := $(COMMON_CFLAGS)
ASFLAGS     := -f elf64
LIBGCC      := $(shell $(CC) -print-libgcc-file-name 2>/dev/null || echo "")
LDFLAGS     := -T linker.ld -nostdlib -z max-page-size=0x1000

BUILD   := build
ISO_DIR := iso

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

$(BUILD)/%.asm.o: src/%.asm
	@mkdir -p $(dir $@)
	$(AS) $(ASFLAGS) $< -o $@

$(BUILD)/boot/%.c.o: src/boot/%.c
	@mkdir -p $(dir $@)
	$(CC) $(BOOT_CFLAGS) -c $< -o $@

$(BUILD)/hal/%.c.o: src/hal/%.c
	@mkdir -p $(dir $@)
	$(CC) $(KERN_CFLAGS) -c $< -o $@

$(BUILD)/libc/%.c.o: src/libc/%.c
	@mkdir -p $(dir $@)
	$(CC) $(KERN_CFLAGS) -c $< -o $@

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
	@cp $(CPYTHON_LIB)/re/__init__.py    $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/re/_compiler.py  $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/re/_parser.py    $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/re/_constants.py $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/re/_casefix.py   $(STDLIB_SHIM)/re/
	@cp $(CPYTHON_LIB)/collections/__init__.py $(STDLIB_SHIM)/collections/
	@cp $(CPYTHON_LIB)/_collections_abc.py     $(STDLIB_SHIM)/collections/abc.py
	@cp tools/stdlib_stubs/inspect.py     $(STDLIB_SHIM)/inspect.py
	@cp tools/stdlib_stubs/pathlib.py     $(STDLIB_SHIM)/pathlib.py
	@cp tools/stdlib_stubs/functools.py   $(STDLIB_SHIM)/functools.py
	@cp tools/stdlib_stubs/dataclasses.py $(STDLIB_SHIM)/dataclasses.py
	@cp tools/stdlib_stubs/os.py          $(STDLIB_SHIM)/os.py
	@cp tools/stdlib_stubs/ctypes/__init__.py $(STDLIB_SHIM)/ctypes/__init__.py
	@cp tools/stdlib_stubs/random.py      $(STDLIB_SHIM)/random.py
	@cp tools/stdlib_stubs/traceback.py   $(STDLIB_SHIM)/traceback.py
	@cp tools/stdlib_stubs/linecache.py   $(STDLIB_SHIM)/linecache.py
	@touch $@

_freeze: $(STDLIB_SHIM)/.stamp
	@mkdir -p $(BUILD)
	python3 tools/freeze_kernel.py kernel asyncio $(ENCODINGS_SRC) \
	    $(STDLIB_SHIM) $(BUILD)/frozen_kernel.c

$(BUILD)/frozen_kernel.o: $(BUILD)/frozen_kernel.c
	@mkdir -p $(BUILD)
	$(CC) $(KERN_CFLAGS) -c $< -o $@

$(KERNEL_ELF): $(BOOT_OBJS) $(HAL_OBJS) $(LIBC_OBJS) \
               $(BUILD)/frozen_kernel.o $(PYTHON_LIB)
	@mkdir -p $(BUILD)
	$(LD) $(LDFLAGS) -o $@ $^ $(LIBGCC)

_iso: $(KERNEL_ELF)
	cp $(KERNEL_ELF) $(ISO_DIR)/boot/pythonos.elf
	grub-mkrescue -o $(ISO_OUT) $(ISO_DIR)
