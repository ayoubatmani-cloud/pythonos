"""
kernel.net.ip — IPv4 encode/decode and checksum.
"""

import struct
from dataclasses import dataclass

PROTO_ICMP = 1
PROTO_TCP  = 6
PROTO_UDP  = 17

def inet_cksum(data: bytes) -> int:
    if len(data) % 2:
        data += b'\x00'
    s = sum(struct.unpack(f">{len(data)//2}H", data))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF

_ip_id = 0   # module-level packet ID counter (can't be a slot on frozen dataclass)

@dataclass(frozen=True, slots=True)
class IPv4Packet:
    src:      bytes   # 4 bytes
    dst:      bytes   # 4 bytes
    proto:    int
    ttl:      int
    payload:  bytes
    tos:      int = 0
    flags:    int = 0x4000  # Don't Fragment

    @classmethod
    def decode(cls, raw: bytes) -> "IPv4Packet":
        if len(raw) < 20:
            raise ValueError("IP packet too short")
        ihl = (raw[0] & 0x0F) * 4
        tos, total_len = raw[1], struct.unpack(">H", raw[2:4])[0]
        flags_frag = struct.unpack(">H", raw[6:8])[0]
        ttl, proto = raw[8], raw[9]
        src, dst   = raw[12:16], raw[16:20]
        return cls(src=src, dst=dst, proto=proto, ttl=ttl,
                   payload=raw[ihl:total_len], tos=tos, flags=flags_frag)

    def encode(self) -> bytes:
        global _ip_id
        _ip_id = (_ip_id + 1) & 0xFFFF
        header = struct.pack(">BBHHHBBH4s4s",
            0x45,               # version=4, IHL=5 (20 bytes)
            self.tos,
            20 + len(self.payload),
            _ip_id,
            self.flags,
            self.ttl,
            self.proto,
            0,                  # checksum placeholder
            self.src,
            self.dst,
        )
        cksum = inet_cksum(header)
        return header[:10] + struct.pack(">H", cksum) + header[12:] + self.payload

def ip_str(addr: bytes) -> str:
    return ".".join(str(b) for b in addr)

def ip_from_str(s: str) -> bytes:
    return bytes(int(p) for p in s.split("."))
