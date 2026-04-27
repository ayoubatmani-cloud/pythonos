"""
Minimal random stub for bare-metal PythonOS.
Uses getrandom() syscall (backed by LFSR in syscalls.c).
"""

import _hal


def _rand32() -> int:
    """Return a random 32-bit unsigned integer."""
    # Use _hal.inl on a port that doesn't exist — actually use getrandom via os
    # Simpler: generate via XOR of port reads; or use os.urandom if available.
    # Best: use the buf_addr trick to read the LFSR seed via our libc
    # Just use a simple LCG seeded from PIT tick count via _hal.inb
    import _hal as _h
    # Read current PIT counter byte as entropy
    low  = _h.inb(0x40)
    high = _h.inb(0x40)
    extra = _h.inb(0x40)
    seed = (high << 16) | (low << 8) | extra
    # Mix with a static counter
    global _state
    _state = (_state * 1664525 + 1013904223 + seed) & 0xFFFFFFFF
    return _state


_state = 0xDEADBEEF


def randint(a: int, b: int) -> int:
    """Return a random integer N such that a <= N <= b."""
    span = b - a + 1
    if span <= 0:
        return a
    if span <= 0xFFFFFFFF:
        return a + (_rand32() % span)
    # For large spans, combine two 32-bit values
    val = (_rand32() << 32) | _rand32()
    return a + (val % span)


def random() -> float:
    """Return a random float in [0.0, 1.0)."""
    return _rand32() / 0x100000000


def uniform(a: float, b: float) -> float:
    return a + (b - a) * random()


def choice(seq):
    if not seq:
        raise IndexError('Cannot choose from an empty sequence')
    return seq[_rand32() % len(seq)]


def shuffle(lst: list) -> None:
    for i in range(len(lst) - 1, 0, -1):
        j = _rand32() % (i + 1)
        lst[i], lst[j] = lst[j], lst[i]


def seed(a=None):
    global _state
    if a is None:
        import _hal as _h
        _state = _h.inb(0x40) ^ (_h.inb(0x40) << 8) ^ 0xDEAD0000
    else:
        _state = int(a) & 0xFFFFFFFF


def getrandbits(k: int) -> int:
    if k <= 32:
        return _rand32() >> (32 - k)
    result = 0
    bits = 0
    while bits < k:
        result = (result << 32) | _rand32()
        bits += 32
    return result >> (bits - k)
