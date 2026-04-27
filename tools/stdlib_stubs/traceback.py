"""Minimal traceback stub for bare-metal PythonOS."""

import sys


def format_exc(limit=None, chain=True):
    """Format the current exception as a string."""
    exc_type, exc_value, exc_tb = sys.exc_info()
    if exc_type is None:
        return 'NoneType: None\n'
    return _format_exception(exc_type, exc_value, exc_tb, limit=limit)


def format_exception(exc, value=None, tb=None, limit=None, chain=True):
    if isinstance(exc, BaseException):
        return _format_exception(type(exc), exc, exc.__traceback__, limit=limit)
    return _format_exception(exc, value, tb, limit=limit)


def format_tb(tb, limit=None):
    return _format_tb(tb, limit)


def print_exc(limit=None, file=None, chain=True):
    if file is None:
        file = sys.stderr
    file.write(format_exc(limit=limit, chain=chain))


def print_exception(exc, value=None, tb=None, limit=None, file=None, chain=True):
    if file is None:
        file = sys.stderr
    if isinstance(exc, BaseException):
        file.write(_format_exception(type(exc), exc, exc.__traceback__, limit=limit))
    else:
        file.write(_format_exception(exc, value, tb, limit=limit))


def _format_tb(tb, limit=None):
    lines = []
    count = 0
    while tb is not None:
        if limit is not None and count >= limit:
            break
        frame = tb.tb_frame
        lineno = tb.tb_lineno
        filename = frame.f_code.co_filename
        name = frame.f_code.co_name
        lines.append(f'  File "{filename}", line {lineno}, in {name}\n')
        count += 1
        tb = tb.tb_next
    return lines


def _format_exception(exc_type, exc_value, exc_tb, limit=None):
    lines = ['Traceback (most recent call last):\n']
    lines.extend(_format_tb(exc_tb, limit=limit))
    lines.append(_format_exception_only(exc_type, exc_value))
    return ''.join(lines)


def _format_exception_only(exc_type, exc_value):
    if exc_type is None:
        return 'None\n'
    name = exc_type.__name__
    msg = str(exc_value) if exc_value is not None else ''
    if msg:
        return f'{name}: {msg}\n'
    return f'{name}\n'


def format_exception_only(exc, value=None):
    if isinstance(exc, type):
        return [_format_exception_only(exc, value)]
    return [_format_exception_only(type(exc), exc)]
