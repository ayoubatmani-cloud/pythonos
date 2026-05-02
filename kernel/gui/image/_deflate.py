"""
Pure-Python RFC 1951 inflate (decompress) — used by the PNG decoder
because the kernel build strips libz.

Implements all three DEFLATE block types:
    BTYPE=00  stored (uncompressed)
    BTYPE=01  fixed Huffman codes
    BTYPE=10  dynamic Huffman codes

Only ~250 LOC; correctness over speed. Tested against PNG IDAT streams
produced by Python's stdlib zlib on the build host.
"""


# ── Length / distance code tables (RFC 1951 §3.2.5) ─────────────────────────

_LENGTH_BASE = [
      3,   4,   5,   6,   7,   8,   9,  10,
     11,  13,  15,  17,  19,  23,  27,  31,
     35,  43,  51,  59,  67,  83,  99, 115,
    131, 163, 195, 227, 258,
]
_LENGTH_EXTRA = [
    0, 0, 0, 0, 0, 0, 0, 0,
    1, 1, 1, 1, 2, 2, 2, 2,
    3, 3, 3, 3, 4, 4, 4, 4,
    5, 5, 5, 5, 0,
]
_DIST_BASE = [
       1,    2,    3,    4,    5,    7,    9,    13,
      17,   25,   33,   49,   65,   97,  129,   193,
     257,  385,  513,  769, 1025, 1537, 2049,  3073,
    4097, 6145, 8193,12289,16385,24577,
]
_DIST_EXTRA = [
    0,  0,  0,  0,  1,  1,  2,  2,
    3,  3,  4,  4,  5,  5,  6,  6,
    7,  7,  8,  8,  9,  9, 10, 10,
   11, 11, 12, 12, 13, 13,
]
_CODE_LEN_ORDER = [16, 17, 18, 0, 8, 7, 9, 6,
                    10,  5, 11, 4,12, 3,13, 2,
                    14, 1, 15]


# ── Bit reader ─────────────────────────────────────────────────────────────

class _BitReader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read_bits(self, n: int) -> int:
        v = 0
        for i in range(n):
            byte = self.data[self.pos >> 3]
            v |= ((byte >> (self.pos & 7)) & 1) << i
            self.pos += 1
        return v

    def align_to_byte(self) -> None:
        self.pos = (self.pos + 7) & ~7

    def read_byte_aligned(self) -> int:
        self.align_to_byte()
        b = self.data[self.pos >> 3]
        self.pos += 8
        return b

    def read_le16_aligned(self) -> int:
        lo = self.read_byte_aligned()
        hi = self.read_byte_aligned()
        return lo | (hi << 8)


# ── Canonical Huffman ───────────────────────────────────────────────────────

class _Huffman:
    __slots__ = ("codes",)

    def __init__(self, lengths: list[int]) -> None:
        # Build canonical Huffman codes from a list of code lengths per
        # RFC 1951 §3.2.2. ``codes`` is a dict mapping (bit_length,
        # bit_code_msb_first) → symbol.
        bl_count = [0] * 16
        for L in lengths:
            if L > 15:
                raise ValueError(f"deflate: huffman code length {L} > 15")
            bl_count[L] += 1
        bl_count[0] = 0

        code = 0
        next_code = [0] * 16
        for bits in range(1, 16):
            code = (code + bl_count[bits - 1]) << 1
            next_code[bits] = code

        self.codes: dict[tuple[int, int], int] = {}
        for n, L in enumerate(lengths):
            if L != 0:
                self.codes[(L, next_code[L])] = n
                next_code[L] += 1

    def decode(self, reader: _BitReader) -> int:
        code = 0
        for L in range(1, 16):
            code = (code << 1) | reader.read_bits(1)
            sym = self.codes.get((L, code))
            if sym != None:
                return sym
        raise ValueError("deflate: invalid huffman code")


# ── Fixed Huffman lengths (RFC 1951 §3.2.6) ────────────────────────────────

def _fixed_lit_lengths() -> list[int]:
    out = [0] * 288
    for i in range(0, 144):
        out[i] = 8
    for i in range(144, 256):
        out[i] = 9
    for i in range(256, 280):
        out[i] = 7
    for i in range(280, 288):
        out[i] = 8
    return out


def _fixed_dist_lengths() -> list[int]:
    return [5] * 32


# ── Inflate driver ──────────────────────────────────────────────────────────

def inflate(data: bytes) -> bytes:
    """Decompress raw DEFLATE-compressed ``data`` (no zlib wrapper)."""
    reader = _BitReader(data)
    out = bytearray()
    while True:
        bfinal = reader.read_bits(1)
        btype  = reader.read_bits(2)

        if btype == 0:
            # Stored block.
            length = reader.read_le16_aligned()
            _nlength = reader.read_le16_aligned()
            for _ in range(length):
                out.append(reader.read_byte_aligned())

        elif btype == 1 or btype == 2:
            if btype == 1:
                lit_lengths  = _fixed_lit_lengths()
                dist_lengths = _fixed_dist_lengths()
            else:
                hlit  = reader.read_bits(5) + 257
                hdist = reader.read_bits(5) + 1
                hclen = reader.read_bits(4) + 4

                code_lens = [0] * 19
                for i in range(hclen):
                    code_lens[_CODE_LEN_ORDER[i]] = reader.read_bits(3)
                code_huffman = _Huffman(code_lens)

                lit_lengths  = []
                dist_lengths = []
                total = hlit + hdist
                while len(lit_lengths) + len(dist_lengths) < total:
                    sym = code_huffman.decode(reader)
                    if sym < 16:
                        # Literal length value (0..15)
                        if len(lit_lengths) < hlit:
                            lit_lengths.append(sym)
                        else:
                            dist_lengths.append(sym)
                    elif sym == 16:
                        # Repeat previous length 3..6 times
                        n = reader.read_bits(2) + 3
                        if len(lit_lengths) + len(dist_lengths) == 0:
                            raise ValueError("deflate: dyn-huffman 16 at start")
                        prev = (dist_lengths[-1] if dist_lengths else lit_lengths[-1])
                        for _ in range(n):
                            if len(lit_lengths) < hlit:
                                lit_lengths.append(prev)
                            else:
                                dist_lengths.append(prev)
                    elif sym == 17:
                        n = reader.read_bits(3) + 3
                        for _ in range(n):
                            if len(lit_lengths) < hlit:
                                lit_lengths.append(0)
                            else:
                                dist_lengths.append(0)
                    elif sym == 18:
                        n = reader.read_bits(7) + 11
                        for _ in range(n):
                            if len(lit_lengths) < hlit:
                                lit_lengths.append(0)
                            else:
                                dist_lengths.append(0)
                    else:
                        raise ValueError(f"deflate: bad len-code {sym}")

            lit_huffman  = _Huffman(lit_lengths)
            dist_huffman = _Huffman(dist_lengths)

            while True:
                sym = lit_huffman.decode(reader)
                if sym < 256:
                    out.append(sym)
                elif sym == 256:
                    break
                else:
                    li = sym - 257
                    if li >= len(_LENGTH_BASE):
                        raise ValueError(f"deflate: bad length code {sym}")
                    length = _LENGTH_BASE[li] + reader.read_bits(_LENGTH_EXTRA[li])
                    dsym = dist_huffman.decode(reader)
                    if dsym >= len(_DIST_BASE):
                        raise ValueError(f"deflate: bad dist code {dsym}")
                    dist = _DIST_BASE[dsym] + reader.read_bits(_DIST_EXTRA[dsym])
                    src = len(out) - dist
                    if src < 0:
                        raise ValueError("deflate: back-reference before start")
                    for k in range(length):
                        out.append(out[src + k])
        else:
            raise ValueError(f"deflate: reserved BTYPE=11")

        if bfinal:
            break

    return bytes(out)


def zlib_inflate(data: bytes) -> bytes:
    """Decompress a zlib-wrapped DEFLATE stream (PNG IDAT, etc.).

    The 2-byte header is validated; the trailing 4-byte Adler-32 is
    *not* checked (sufficient for our use case).
    """
    if len(data) < 6:
        raise ValueError("zlib: stream too short")
    cmf = data[0]
    flg = data[1]
    if (cmf & 0x0F) != 8:
        raise ValueError(f"zlib: unsupported CM={cmf & 0x0F}")
    if ((cmf << 8) | flg) % 31 != 0:
        raise ValueError("zlib: header check failed")
    if flg & 0x20:
        raise ValueError("zlib: preset dictionary not supported")
    return inflate(data[2:-4])
