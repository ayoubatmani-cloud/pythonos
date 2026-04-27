"""
Minimal ctypes stub for bare-metal PythonOS.

Provides only the subset used by kernel drivers:
  - c_uint8, c_uint16, c_uint32, c_uint64
  - Array types: (c_uint8 * N)()
  - addressof(buf) — returns physical address via _hal.buf_addr()

On bare metal with identity mapping, virtual address == physical address.
"""

import _hal


def addressof(obj):
    """Return the physical address of obj's internal buffer."""
    return _hal.buf_addr(obj)


class _SimpleType:
    """Base for simple ctypes scalar types."""
    _size_ = 1

    def __init__(self, val=0):
        self._val = int(val)

    def __int__(self):
        return self._val

    def __index__(self):
        return self._val

    class _ArrayMeta(type):
        def __mul__(cls, count):
            size = cls._size_
            outer_cls = cls

            class _Array(bytearray):
                _length_ = count
                _type_ = outer_cls
                _elem_size = size

                def __new__(subcls, *args):
                    if args:
                        # Initialise from sequence of ints
                        data = bytearray(count * size)
                        for i, v in enumerate(args):
                            data[i * size] = int(v) & 0xFF
                        return bytearray.__new__(subcls, data)
                    return bytearray.__new__(subcls, count * size)

                def __getitem__(self, idx):
                    if isinstance(idx, slice):
                        return bytearray.__getitem__(self, idx)
                    return bytearray.__getitem__(self, idx * self._elem_size)

                def __setitem__(self, idx, val):
                    if isinstance(idx, slice):
                        bytearray.__setitem__(self, idx, val)
                    else:
                        bytearray.__setitem__(self, idx * self._elem_size, int(val) & 0xFF)

                def __len__(self):
                    return self._length_

            _Array.__name__ = f'{outer_cls.__name__}_Array_{count}'
            return _Array

    # Attach metaclass to _SimpleType
    class _Meta(_ArrayMeta):
        pass


# Redefine _SimpleType using the metaclass properly
class _SimpleTypeMeta(type):
    def __mul__(cls, count):
        size = cls._size_
        outer_cls = cls

        class _Array(bytearray):
            _length_ = count
            _type_ = outer_cls
            _elem_size = size

            def __new__(subcls, *args):
                if args:
                    data = bytearray(count * size)
                    for i, v in enumerate(args):
                        data[i * size] = int(v) & 0xFF
                    return bytearray.__new__(subcls, data)
                return bytearray.__new__(subcls, count * size)

            def __getitem__(self, idx):
                if isinstance(idx, slice):
                    return bytearray.__getitem__(self, idx)
                return bytearray.__getitem__(self, idx * self._elem_size)

            def __setitem__(self, idx, val):
                if isinstance(idx, slice):
                    bytearray.__setitem__(self, idx, val)
                else:
                    bytearray.__setitem__(self, idx * self._elem_size, int(val) & 0xFF)

            def __len__(self):
                return self._length_

        _Array.__name__ = f'{outer_cls.__name__}_Array_{count}'
        return _Array


class c_uint8(metaclass=_SimpleTypeMeta):
    _size_ = 1
    def __init__(self, val=0): self._val = int(val) & 0xFF
    def __int__(self): return self._val


class c_uint16(metaclass=_SimpleTypeMeta):
    _size_ = 2
    def __init__(self, val=0): self._val = int(val) & 0xFFFF
    def __int__(self): return self._val


class c_uint32(metaclass=_SimpleTypeMeta):
    _size_ = 4
    def __init__(self, val=0): self._val = int(val) & 0xFFFFFFFF
    def __int__(self): return self._val


class c_uint64(metaclass=_SimpleTypeMeta):
    _size_ = 8
    def __init__(self, val=0): self._val = int(val) & 0xFFFFFFFFFFFFFFFF
    def __int__(self): return self._val


# Aliases
c_ubyte = c_uint8
c_ushort = c_uint16
c_uint = c_uint32
c_ulong = c_uint64
c_ulonglong = c_uint64
