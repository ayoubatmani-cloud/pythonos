"""
pathlib.py — minimal stub for PythonOS bare-metal kernel.

Provides PurePosixPath, which kernel/fs/vfs.py imports.
Does NOT try to touch the filesystem.
"""


class PurePath:
    def __init__(self, *args):
        if not args:
            self._str = '.'
        else:
            parts = []
            for a in args:
                parts.append(str(a))
            self._str = '/'.join(parts)
        # Normalize double slashes but keep leading /
        while '//' in self._str:
            self._str = self._str.replace('//', '/')
        if not self._str:
            self._str = '.'

    def __str__(self):
        return self._str

    def __repr__(self):
        return f'{type(self).__name__}({self._str!r})'

    def __eq__(self, other):
        if isinstance(other, PurePath):
            return self._str == other._str
        return NotImplemented

    def __hash__(self):
        return hash(self._str)

    def __truediv__(self, other):
        other = str(other)
        if other.startswith('/'):
            return type(self)(other)
        return type(self)(self._str.rstrip('/') + '/' + other)

    def __rtruediv__(self, other):
        return type(self)(other) / self._str

    @property
    def parts(self):
        s = self._str
        if s == '/':
            return ('/',)
        if s.startswith('/'):
            return ('/',) + tuple(s[1:].split('/'))
        return tuple(s.split('/'))

    @property
    def parent(self):
        s = self._str
        if '/' not in s or s == '/':
            return type(self)('.')
        idx = s.rfind('/')
        if idx == 0:
            return type(self)('/')
        return type(self)(s[:idx])

    @property
    def name(self):
        return self._str.rsplit('/', 1)[-1]

    @property
    def suffix(self):
        name = self.name
        idx = name.rfind('.')
        return name[idx:] if idx > 0 else ''

    @property
    def suffixes(self):
        name = self.name
        parts = name.split('.')
        return ['.' + p for p in parts[1:]]

    @property
    def stem(self):
        name = self.name
        idx = name.rfind('.')
        return name[:idx] if idx > 0 else name

    def with_name(self, name):
        return self.parent / name

    def with_suffix(self, suffix):
        return self.parent / (self.stem + suffix)

    def is_absolute(self):
        return self._str.startswith('/')

    def __fspath__(self):
        return self._str


class PurePosixPath(PurePath):
    pass


class PureWindowsPath(PurePath):
    pass


class Path(PurePosixPath):
    def exists(self):
        return False

    def is_dir(self):
        return False

    def is_file(self):
        return False

    def stat(self):
        raise FileNotFoundError(self._str)

    def open(self, *args, **kwargs):
        raise FileNotFoundError(self._str)

    def read_bytes(self):
        raise FileNotFoundError(self._str)

    def read_text(self, *args, **kwargs):
        raise FileNotFoundError(self._str)

    def iterdir(self):
        return iter([])

    def mkdir(self, *args, **kwargs):
        pass
