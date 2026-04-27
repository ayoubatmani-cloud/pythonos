"""
kernel.net.arp — ARP (Address Resolution Protocol) for IPv4 over Ethernet.
"""

import asyncio
import struct
from kernel.net.ethernet import EtherFrame, ETHERTYPE_ARP, BROADCAST_MAC

ARP_REQUEST = 1
ARP_REPLY   = 2

class ARPTable:
    def __init__(self) -> None:
        self._table: dict[bytes, bytes] = {}   # IPv4 -> MAC
        self._pending: dict[bytes, asyncio.Future] = {}

    def learn(self, ip: bytes, mac: bytes) -> None:
        self._table[ip] = mac
        fut = self._pending.pop(ip, None)
        if fut and not fut.done():
            fut.set_result(mac)

    def lookup(self, ip: bytes) -> bytes | None:
        return self._table.get(ip)

    async def resolve(self, ip: bytes, timeout: float = 3.0) -> bytes | None:
        mac = self._table.get(ip)
        if mac:
            return mac
        fut: asyncio.Future[bytes] = asyncio.get_event_loop().create_future()
        self._pending[ip] = fut
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(ip, None)
            return None

    def build_request(self, sender_mac: bytes, sender_ip: bytes,
                      target_ip: bytes) -> bytes:
        arp = struct.pack(">HHBBH6s4s6s4s",
            1,           # HTYPE: Ethernet
            0x0800,      # PTYPE: IPv4
            6,           # HLEN
            4,           # PLEN
            ARP_REQUEST,
            sender_mac,
            sender_ip,
            bytes(6),    # target MAC unknown
            target_ip,
        )
        return EtherFrame(
            dst=BROADCAST_MAC,
            src=sender_mac,
            ethertype=ETHERTYPE_ARP,
            payload=arp,
        ).encode()

    def handle_frame(self, payload: bytes) -> None:
        if len(payload) < 28:
            return
        op          = struct.unpack(">H", payload[6:8])[0]
        sender_mac  = payload[8:14]
        sender_ip   = payload[14:18]
        self.learn(sender_ip, sender_mac)

# Module-level singleton
arp_table = ARPTable()
