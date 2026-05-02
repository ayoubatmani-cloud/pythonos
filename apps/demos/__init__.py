"""apps.demos — Built-in graphics + audio demos."""

# Import order matters: each module's top-level register() call needs to
# fire when ``apps.demos`` is imported.
from apps.demos import bouncing_ball  # noqa: F401
from apps.demos import audio_tone     # noqa: F401
