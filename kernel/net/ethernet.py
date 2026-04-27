"""
kernel.net.ethernet — Ethernet frame encode/decode.
"""

import struct
from dataclasses import dataclass

ETHERTYPE_IPv4 = 0x0800
ETHERTYPE_ARP  = 0x0806
ETHERTYPE_IPv6 = 0x86DD

BROADCAST_MAC  = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
ZERO_MAC       = bytes(6)

@dataclass(frozen=True, slots=True)
class EtherFrame:
    dst:      bytes   # 6 bytes
    src:      bytes   # 6 bytes
    ethertype: int
    payload:  bytes

    @classmethod
    def decode(cls, raw: bytes) -> "EtherFrame":
        if len(raw) < 14:
            raise ValueError("Frame too short")
        dst, src = raw[0:6], raw[6:12]
        ethertype = struct.unpack(">H", raw[12:14])[0]
        return cls(dst=dst, src=src, ethertype=ethertype, payload=raw[14:])

    def encode(self) -> bytes:
        return self.dst + self.src + struct.pack(">H", self.ethertype) + self.payload

def mac_str(mac: bytes) -> str:
    return ":".join(f"{b:02x}" for b in mac)
