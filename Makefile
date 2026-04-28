# BSD make stub — delegates everything to GNU make.
# GNU make (gmake) is required; on macOS: brew install make
#
# GNU make prefers GNUMakefile over Makefile, so on systems where
# 'make' is already GNU make this file is never read.

# Prefer gmake (Homebrew GNU make) if present; fall back to make (GNU make 3.81 on macOS)
GMAKE ?= $(if $(shell which gmake 2>/dev/null),gmake,make)

.PHONY: all
all:
	@$(GMAKE) -f GNUMakefile

.DEFAULT:
	@$(GMAKE) -f GNUMakefile $@
