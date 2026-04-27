# BSD make stub — delegates everything to GNU make.
# GNU make (gmake) is required; on macOS: brew install make
#
# GNU make prefers GNUMakefile over Makefile, so on systems where
# 'make' is already GNU make this file is never read.

GMAKE ?= gmake

.PHONY: all
all:
	@$(GMAKE) -f GNUMakefile

.DEFAULT:
	@$(GMAKE) -f GNUMakefile $@
