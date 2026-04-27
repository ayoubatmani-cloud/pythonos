"""
dataclasses.py — exec()-free stub for PythonOS bare-metal kernel.

The CPython dataclasses module uses exec() to generate __init__ etc.
exec() fails on bare-metal Python (the compiler crashes on dynamically
compiled strings). This stub uses closures instead.

Supports: @dataclass, @dataclass(frozen=True), @dataclass(slots=True),
          @dataclass(frozen=True, slots=True), field(), fields(), Field,
          FrozenInstanceError, MISSING, KW_ONLY, asdict(), astuple().
"""

import sys
import copy

__all__ = [
    'dataclass', 'field', 'Field', 'FrozenInstanceError', 'KW_ONLY',
    'MISSING', 'fields', 'asdict', 'astuple', 'make_dataclass',
    'replace',
]


class _MISSING_TYPE:
    def __repr__(self): return 'MISSING'

MISSING = _MISSING_TYPE()


class _KW_ONLY_TYPE:
    pass

KW_ONLY = _KW_ONLY_TYPE()


class FrozenInstanceError(AttributeError):
    pass


class Field:
    __slots__ = ('name', 'type', 'default', 'default_factory',
                 'repr', 'hash', 'init', 'compare', 'metadata',
                 'kw_only', '_field_type')

    def __init__(self, default, default_factory, init, repr, hash,
                 compare, metadata, kw_only):
        self.name = None
        self.type = None
        self.default = default
        self.default_factory = default_factory
        self.init = init
        self.repr = repr
        self.hash = hash
        self.compare = compare
        self.metadata = metadata if metadata is not None else {}
        self.kw_only = kw_only
        self._field_type = None

    def __repr__(self):
        return (f'Field(name={self.name!r}, type={self.type!r}, '
                f'default={self.default!r})')


def field(*, default=MISSING, default_factory=MISSING, init=True,
          repr=True, hash=None, compare=True, metadata=None, kw_only=MISSING):
    if default is not MISSING and default_factory is not MISSING:
        raise TypeError('cannot specify both default and default_factory')
    return Field(default, default_factory, init, repr, hash, compare,
                 metadata, kw_only)


def _get_fields(cls):
    """Extract Field objects from a class's annotations, in order."""
    result = []
    anns = {}
    for base in reversed(cls.__mro__):
        if base is object:
            continue
        a = base.__dict__.get('__annotations__', {})
        anns.update(a)
    anns = cls.__dict__.get('__annotations__', {})

    for name, tp in anns.items():
        if isinstance(tp, type) and tp is _KW_ONLY_TYPE:
            continue
        val = cls.__dict__.get(name, MISSING)
        if isinstance(val, Field):
            f = val
        else:
            f = Field(default=val, default_factory=MISSING,
                      init=True, repr=True, hash=None,
                      compare=True, metadata=None, kw_only=MISSING)
        f.name = name
        f.type = tp
        result.append(f)
    return result


def _make_init(fs, frozen, has_post_init):
    """Return a closure-based __init__ for the given fields."""
    init_fields = [f for f in fs if f.init]

    # pre-check: fields with defaults must come after fields without
    seen_default = False
    for f in init_fields:
        has_def = (f.default is not MISSING or f.default_factory is not MISSING)
        if has_def:
            seen_default = True
        elif seen_default:
            raise TypeError(
                f'non-default argument {f.name!r} follows default argument')

    if frozen:
        def __init__(self, *args, **kwargs):
            # positional args
            for i, f in enumerate(init_fields):
                if i < len(args):
                    object.__setattr__(self, f.name, args[i])
                elif f.name in kwargs:
                    object.__setattr__(self, f.name, kwargs.pop(f.name))
                elif f.default is not MISSING:
                    object.__setattr__(self, f.name, f.default)
                elif f.default_factory is not MISSING:
                    object.__setattr__(self, f.name, f.default_factory())
                else:
                    raise TypeError(
                        f'__init__() missing required argument: {f.name!r}')
            if kwargs:
                raise TypeError(f'__init__() got unexpected keyword arguments: '
                                f'{list(kwargs)!r}')
            if has_post_init:
                self.__dataclass_post_init__()
    else:
        def __init__(self, *args, **kwargs):
            for i, f in enumerate(init_fields):
                if i < len(args):
                    setattr(self, f.name, args[i])
                elif f.name in kwargs:
                    setattr(self, f.name, kwargs.pop(f.name))
                elif f.default is not MISSING:
                    setattr(self, f.name, f.default)
                elif f.default_factory is not MISSING:
                    setattr(self, f.name, f.default_factory())
                else:
                    raise TypeError(
                        f'__init__() missing required argument: {f.name!r}')
            if kwargs:
                raise TypeError(f'__init__() got unexpected keyword arguments: '
                                f'{list(kwargs)!r}')
            if has_post_init:
                self.__dataclass_post_init__()
    return __init__


def _make_repr(fs):
    repr_fields = [f for f in fs if f.repr]
    def __repr__(self):
        parts = ', '.join(
            f'{f.name}={getattr(self, f.name)!r}' for f in repr_fields
        )
        return f'{type(self).__qualname__}({parts})'
    return __repr__


def _make_eq(fs):
    eq_fields = [f for f in fs if f.compare]
    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return all(
            getattr(self, f.name) == getattr(other, f.name)
            for f in eq_fields
        )
    return __eq__


def _make_hash(fs):
    hash_fields = [f for f in fs if f.compare]
    def __hash__(self):
        return hash(tuple(getattr(self, f.name) for f in hash_fields))
    return __hash__


def _make_frozen_setattr(fs):
    field_names = frozenset(f.name for f in fs)
    def __setattr__(self, name, value):
        if name in field_names:
            raise FrozenInstanceError(f'cannot assign to field {name!r}')
        object.__setattr__(self, name, value)
    return __setattr__


def _make_frozen_delattr(fs):
    field_names = frozenset(f.name for f in fs)
    def __delattr__(self, name):
        if name in field_names:
            raise FrozenInstanceError(f'cannot delete field {name!r}')
        object.__delattr__(self, name)
    return __delattr__


def _process_class(cls, init, repr, eq, order, unsafe_hash, frozen,
                   match_args, kw_only, slots, weakref_slot):
    fs = _get_fields(cls)
    has_post_init = hasattr(cls, '__dataclass_post_init__')

    # Validate: frozen fields can't have mutable defaults
    for f in fs:
        if (f.default is not MISSING and
                isinstance(f.default, (list, dict, set))):
            raise ValueError(
                f'mutable default {type(f.default)!r} for field '
                f'{f.name!r} is not allowed: use default_factory')

    # Mark the class as a dataclass
    cls.__dataclass_fields__ = {f.name: f for f in fs}

    if slots:
        slot_names = [f.name for f in fs]
        # Build namespace for the new slotted class
        ns = {'__module__': cls.__module__,
              '__qualname__': cls.__qualname__,
              '__doc__': cls.__doc__,
              '__annotations__': dict(cls.__dict__.get('__annotations__', {})),
              '__slots__': tuple(slot_names)}
        # Copy non-field class members
        for k, v in cls.__dict__.items():
            if k in ('__dict__', '__weakref__', '__annotations__'):
                continue
            if k in slot_names:
                continue
            ns[k] = v
        bases = cls.__bases__
        cls = type(cls)(cls.__name__, bases, ns)
        cls.__dataclass_fields__ = {f.name: f for f in fs}

    if init and '__init__' not in cls.__dict__:
        cls.__init__ = _make_init(fs, frozen, has_post_init)

    if repr and '__repr__' not in cls.__dict__:
        cls.__repr__ = _make_repr(fs)

    if eq and '__eq__' not in cls.__dict__:
        cls.__eq__ = _make_eq(fs)
        if not unsafe_hash:
            cls.__hash__ = _make_hash(fs) if frozen else None

    if frozen:
        cls.__setattr__ = _make_frozen_setattr(fs)
        cls.__delattr__ = _make_frozen_delattr(fs)

    if unsafe_hash:
        cls.__hash__ = _make_hash(fs)

    return cls


def dataclass(cls=None, /, *, init=True, repr=True, eq=True, order=False,
              unsafe_hash=False, frozen=False, match_args=True,
              kw_only=False, slots=False, weakref_slot=False):
    def wrap(cls):
        return _process_class(cls, init=init, repr=repr, eq=eq, order=order,
                               unsafe_hash=unsafe_hash, frozen=frozen,
                               match_args=match_args, kw_only=kw_only,
                               slots=slots, weakref_slot=weakref_slot)
    if cls is None:
        return wrap
    return wrap(cls)


def fields(class_or_instance):
    try:
        fs = class_or_instance.__dataclass_fields__
    except AttributeError:
        raise TypeError('has no dataclass fields') from None
    return tuple(fs.values())


def asdict(obj, *, dict_factory=dict):
    if not hasattr(obj, '__dataclass_fields__'):
        raise TypeError('asdict() should be called on dataclass instances')
    return _asdict_inner(obj, dict_factory)


def _asdict_inner(obj, dict_factory):
    if hasattr(obj, '__dataclass_fields__'):
        result = []
        for f in obj.__dataclass_fields__.values():
            value = _asdict_inner(getattr(obj, f.name), dict_factory)
            result.append((f.name, value))
        return dict_factory(result)
    elif isinstance(obj, (list, tuple)):
        return type(obj)(_asdict_inner(v, dict_factory) for v in obj)
    elif isinstance(obj, dict):
        return type(obj)((_asdict_inner(k, dict_factory),
                          _asdict_inner(v, dict_factory))
                         for k, v in obj.items())
    else:
        return copy.deepcopy(obj)


def astuple(obj, *, tuple_factory=tuple):
    if not hasattr(obj, '__dataclass_fields__'):
        raise TypeError('astuple() should be called on dataclass instances')
    return _astuple_inner(obj, tuple_factory)


def _astuple_inner(obj, tuple_factory):
    if hasattr(obj, '__dataclass_fields__'):
        result = [_astuple_inner(getattr(obj, f.name), tuple_factory)
                  for f in obj.__dataclass_fields__.values()]
        return tuple_factory(result)
    elif isinstance(obj, (list, tuple)):
        return type(obj)(_astuple_inner(v, tuple_factory) for v in obj)
    elif isinstance(obj, dict):
        return type(obj)((_astuple_inner(k, tuple_factory),
                          _astuple_inner(v, tuple_factory))
                         for k, v in obj.items())
    else:
        return copy.deepcopy(obj)


def replace(obj, /, **changes):
    if not hasattr(obj, '__dataclass_fields__'):
        raise TypeError('replace() should be called on dataclass instances')
    fs = obj.__dataclass_fields__
    for k in changes:
        if k not in fs:
            raise TypeError(f'replace() got an unexpected field name: {k!r}')
    kwargs = {f.name: changes.get(f.name, getattr(obj, f.name))
              for f in fs.values()}
    return type(obj)(**kwargs)


def make_dataclass(cls_name, fields, *, bases=(), namespace=None,
                   init=True, repr=True, eq=True, order=False,
                   unsafe_hash=False, frozen=False, match_args=True,
                   kw_only=False, slots=False, weakref_slot=False,
                   module=None):
    anns = {}
    defaults = {}
    for item in fields:
        if isinstance(item, str):
            name = item
            tp = object
        elif len(item) == 2:
            name, tp = item
        else:
            name, tp, spec = item
            defaults[name] = spec
    anns[name] = tp

    ns = {'__annotations__': anns}
    if namespace:
        ns.update(namespace)
    ns.update(defaults)
    cls = type(cls_name, bases or (object,), ns)
    return dataclass(cls, init=init, repr=repr, eq=eq, order=order,
                     unsafe_hash=unsafe_hash, frozen=frozen,
                     match_args=match_args, kw_only=kw_only,
                     slots=slots, weakref_slot=weakref_slot)
