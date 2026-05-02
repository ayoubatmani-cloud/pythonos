"""sdl2 — top-level alias for the PySDL2-compatible kernel.gui.sdl2 package.

Lets unmodified PySDL2 programs ``import sdl2`` and find the same surface
PySDL2 itself exposes, dispatched into our compositor / input / mixer.
"""

from kernel.gui.sdl2 import *  # noqa: F401,F403
