"""
inspect.py — minimal stub for PythonOS bare-metal kernel.

Only implements what dataclasses.py needs at import/decoration time.
Does NOT import dis, opcode, or anything requiring _opcode C extension.
"""


class Format:
    VALUE      = 1
    STRING     = 2
    FORWARDREF = 3


def get_annotations(obj, *, globals=None, locals=None, eval_str=False, format=None):
    """Return the annotations dict for obj (class, function, or module)."""
    if isinstance(obj, type):
        ann = obj.__dict__.get('__annotations__', {})
    else:
        ann = getattr(obj, '__annotations__', {})
    if not ann:
        return {}
    ann = dict(ann)
    if eval_str:
        g = globals or {}
        l = locals or {}
        ann = {k: eval(v, g, l) if isinstance(v, str) else v for k, v in ann.items()}
    return ann


def signature(obj, *args, **kwargs):
    raise ValueError('inspect.signature is not supported on bare metal')


def isfunction(obj):
    return isinstance(obj, type(lambda: None))


def isclass(obj):
    return isinstance(obj, type)


def ismodule(obj):
    import sys
    return isinstance(obj, type(sys))


def isbuiltin(obj):
    return isinstance(obj, type(len))


def isroutine(obj):
    return callable(obj)


def iscoroutinefunction(func):
    return (getattr(func, '__wrapped__', None) is not None
            and iscoroutinefunction(func.__wrapped__))


def getmembers(obj, predicate=None):
    results = []
    for name in dir(obj):
        try:
            value = getattr(obj, name)
        except AttributeError:
            continue
        if predicate is None or predicate(value):
            results.append((name, value))
    return results
