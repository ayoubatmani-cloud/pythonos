"""apps.editor.edwin — `ed` line editor in a compositor window.

Reuses :class:`apps._textwin.TextWin` so the existing
:func:`kernel.ed.run` (which talks to the world via ``write`` and
``read_char`` callables) drops in unmodified.
"""

from kernel.gui.compositor import compositor, CompositorWindow
from kernel.ed import run as _ed_run
from apps import registry
from apps._textwin import TextWin


async def main(argv=None, *args, **kwargs) -> None:
    argv = list(argv) if argv else []
    title = "Editor: " + (argv[0] if argv else "(no file)")
    win = CompositorWindow(title, x=120, y=120, w=720, h=480)
    compositor.add_window(win)
    view = TextWin(win)
    win.set_event_handler(view.on_event)

    # Banner so empty-file sessions look intentional.
    view.write("PythonOS ed — type ':' or '?' for help, 'q' to quit.\n")
    try:
        await _ed_run(argv, "/", view.write, view.read_char)
    finally:
        win.close()


registry.register(
    name="editor",
    description="ed-style line editor",
    entry=main,
)
