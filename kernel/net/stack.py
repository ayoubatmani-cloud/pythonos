"""
kernel.net.stack — Network stack glue.

Receives Ethernet frames from the NIC driver, demultiplexes by EtherType,
and hands off to ARP, IP, and higher-level protocol handlers.
Also provides the send path: TCP → IP → Ethernet → NIC.
"""


import asyncio
from kernel.net.ethernet import EtherFrame, ETHERTYPE_IPv4, ETHERTYPE_ARP
from kernel.net.ip       import IPv4Packet, ip_str
from kernel.net.arp      import arp_table
import kernel.log as log

# Our interface configuration (set by DHCP or static config at boot)
local_ip:  bytes = bytes(4)   # 0.0.0.0 until configured
local_mac: bytes = bytes(6)
gateway:   bytes = bytes(4)
netmask:   bytes = bytes(4)

# The active NIC driver (set by net_init())
_nic = None

async def net_init(nic, ip: str, gw: str, mask: str = "255.255.255.0") -> None:
    """Configure the network stack with a static IP."""
    global local_ip, local_mac, gateway, netmask, _nic
    from kernel.net.ip import ip_from_str
    _nic       = nic
    local_mac  = nic.mac
    local_ip   = ip_from_str(ip)
    gateway    = ip_from_str(gw)
    netmask    = ip_from_str(mask)
    log.info(f"net: configured {ip} gw={gw}")
    asyncio.ensure_future(_rx_loop())

async def _rx_loop() -> None:
    """Continuously receive and dispatch Ethernet frames."""
    while True:
        raw = await _nic.recv()
        if len(raw) < 14:
            continue
        try:
            frame = EtherFrame.decode(raw)
            await _dispatch(frame)
        except Exception as e:
            log.warn(f"net: rx error: {e}")

async def _dispatch(frame: EtherFrame) -> None:
    if frame.ethertype == ETHERTYPE_ARP:
        arp_table.handle_frame(frame.payload)
    elif frame.ethertype == ETHERTYPE_IPv4:
        pkt = IPv4Packet.decode(frame.payload)
        from kernel.net.tcp import tcp
        tcp.handle_ip_packet(pkt)
    # IPv6 — future

async def send_tcp_segment(seg, src_ip: bytes, dst_ip: bytes) -> None:
    """Wrap a TCP segment in IP and Ethernet and transmit it."""
    if _nic is None:
        return
    # Resolve next-hop MAC via ARP
    from kernel.net.ip import ip_from_str
    if dst_ip[:3] == local_ip[:3]:   # same /24 subnet (rough check)
        next_hop = dst_ip
    else:
        next_hop = gateway

    mac = arp_table.lookup(next_hop)
    if mac is None:
        arp_req = arp_table.build_request(local_mac, local_ip, next_hop)
        await _nic.send(arp_req[14:])   # send without Ethernet header (NIC adds it)
        mac = await arp_table.resolve(next_hop)
        if mac is None:
            log.warn(f"net: ARP timeout for {ip_str(next_hop)}")
            return

    ip_pkt   = IPv4Packet(src=src_ip or local_ip, dst=dst_ip,
                          proto=6, ttl=64,
                          payload=seg.encode(src_ip or local_ip, dst_ip))
    eth_frame = EtherFrame(dst=mac, src=local_mac,
                           ethertype=ETHERTYPE_IPv4,
                           payload=ip_pkt.encode())
    await _nic.send(eth_frame.encode())
