"""
os.py — minimal stub for PythonOS bare-metal kernel.

Provides what contextlib, posixpath, and kernel code need.
Does NOT import posix (which fails on bare metal due to missing _have_functions).
"""

import sys
import posixpath

# Basic identity
name = 'posix'
linesep = '\n'
sep     = '/'
altsep  = None
extsep  = '.'
curdir  = '.'
pardir  = '..'
pathsep = ':'
defpath = '/bin:/usr/bin'
devnull = '/dev/null'

path = posixpath

# Aliases expected from os.path
from posixpath import (
    join, split, splitext, dirname, basename, abspath, realpath,
    isabs, isfile, isdir, exists, normpath, expanduser, expandvars,
    commonprefix, relpath,
)

# Empty environment on bare metal
environ = {}


def getcwd():
    return '/'


def chdir(path):
    pass


def getenv(key, default=None):
    return environ.get(key, default)


def fspath(path):
    if isinstance(path, (str, bytes)):
        return path
    path_type = type(path)
    try:
        path_repr = path_type.__fspath__(path)
    except AttributeError:
        if hasattr(path_type, '__fspath__'):
            raise
        raise TypeError(
            f'expected str, bytes or os.PathLike object, not {path_type.__name__!r}')
    if isinstance(path_repr, (str, bytes)):
        return path_repr
    raise TypeError(
        f'expected {path_type.__name__}.__fspath__() to return str or bytes, '
        f'not {type(path_repr).__name__!r}')


def getpid():
    return 1


def getuid():
    return 0


def getgid():
    return 0


def listdir(path='.'):
    return []


def stat(path, *, dir_fd=None, follow_symlinks=True):
    raise FileNotFoundError(path)


def lstat(path, *, dir_fd=None):
    raise FileNotFoundError(path)


def access(path, mode, *, dir_fd=None, effective_ids=False, follow_symlinks=True):
    return False


def strerror(code):
    return f'Error {code}'


# Supports sets — empty on bare metal
supports_dir_fd        = set()
supports_effective_ids = set()
supports_fd            = set()
supports_follow_symlinks = set()

# Open flags
O_RDONLY  = 0
O_WRONLY  = 1
O_RDWR    = 2
O_CREAT   = 64
O_TRUNC   = 512
O_APPEND  = 1024
O_EXCL    = 128

SEEK_SET = 0
SEEK_CUR = 1
SEEK_END = 2

F_OK = 0
R_OK = 4
W_OK = 2
X_OK = 1


class PathLike:
    """Abstract base class for path-like objects."""
    def __fspath__(self):
        raise NotImplementedError


def open(path, flags, mode=0o777, *, dir_fd=None):
    raise OSError(f'open not supported on bare metal: {path!r}')


def close(fd):
    pass


def read(fd, n):
    raise OSError('read not supported on bare metal')


def write(fd, b):
    raise OSError('write not supported on bare metal')


def makedirs(name, mode=0o777, exist_ok=False):
    pass


def mkdir(path, mode=0o777, *, dir_fd=None):
    pass


def remove(path, *, dir_fd=None):
    raise FileNotFoundError(path)


def unlink(path, *, dir_fd=None):
    raise FileNotFoundError(path)


def rename(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
    raise OSError('rename not supported on bare metal')


# Ensure os.path is accessible as sys.modules['os.path']
sys.modules['os.path'] = posixpath

__all__ = [
    'name', 'linesep', 'sep', 'altsep', 'extsep', 'curdir', 'pardir',
    'pathsep', 'defpath', 'devnull', 'path', 'environ',
    'getcwd', 'chdir', 'getenv', 'fspath', 'getpid', 'getuid', 'getgid',
    'listdir', 'stat', 'lstat', 'access', 'strerror',
    'supports_dir_fd', 'supports_effective_ids', 'supports_fd',
    'supports_follow_symlinks',
    'O_RDONLY', 'O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_TRUNC', 'O_APPEND',
    'O_EXCL', 'SEEK_SET', 'SEEK_CUR', 'SEEK_END',
    'F_OK', 'R_OK', 'W_OK', 'X_OK', 'PathLike',
    'open', 'close', 'read', 'write', 'makedirs', 'mkdir',
    'remove', 'unlink', 'rename',
    'join', 'split', 'splitext', 'dirname', 'basename', 'abspath',
    'realpath', 'isabs', 'isfile', 'isdir', 'exists', 'normpath',
    'expanduser', 'expandvars', 'commonprefix', 'relpath',
]
