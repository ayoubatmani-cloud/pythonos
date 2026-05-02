"""
apps — PythonOS built-in GUI applications.

Apps register themselves with :mod:`apps.registry` so the
``pythonos_gui`` launcher can list and start them. Each app is a
package with a ``main()`` coroutine that takes a CompositorWindow
(or constructs its own and adds it via the compositor singleton).
"""
