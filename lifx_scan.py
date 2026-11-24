#!/usr/bin/env python3
"""Unicast-sweep a /24 for LIFX bulbs (works through WSL NAT where broadcast doesn't)."""
import socket, struct, sys, time

SUBNET = sys.argv[1] if len(sys.argv) > 1 else "192.168.2"
PORT = 56700
SOURCE = 0x4C494658  # arbitrary client id


def packet(msg_type, payload=b"", target=b"\x00" * 8, tagged=True, res=True, seq=0):
    size = 36 + len(payload)
    proto = 1024 | (1 << 12) | ((1 << 13) if tagged else 0)
    frame = struct.pack("<HHI", size, proto, SOURCE)
    addr = target + b"\x00" * 6 + struct.pack("<BB", 1 if res else 0, seq)
    hdr = struct.pack("<QHH", 0, msg_type, 0)
    return frame + addr + hdr + payload


def mac(b):
    return ":".join(f"{x:02X}" for x in b[:6])


s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("", 0))
s.settimeout(0.2)

found = {}
for rnd in range(2):
    for i in range(1, 255):
        s.sendto(packet(2), (f"{SUBNET}.{i}", PORT))  # GetService
        time.sleep(0.002)
    end = time.time() + 2
    while time.time() < end:
        try:
            data, (ip, _) = s.recvfrom(1024)
        except socket.timeout:
            continue
        if len(data) >= 36 and struct.unpack_from("<H", data, 32)[0] == 3:
            found[ip] = data[8:16]

# Ask each bulb for its state (label, power, colour)
for ip, tgt in sorted(found.items(), key=lambda kv: int(kv[0].rsplit(".", 1)[1])):
    label, power = "?", "?"
    s.sendto(packet(101, target=tgt, tagged=False), (ip, PORT))  # GetColor
    end = time.time() + 1
    while time.time() < end:
        try:
            data, (rip, _) = s.recvfrom(1024)
        except socket.timeout:
            continue
        if rip == ip and struct.unpack_from("<H", data, 32)[0] == 107:  # LightState
            h, sa, b, k = struct.unpack_from("<HHHH", data, 36)
            power = "on" if struct.unpack_from("<H", data, 46)[0] else "off"
            label = data[48:80].split(b"\x00")[0].decode(errors="replace")
            break
    print(f"{ip:15} {mac(tgt)}  power={power:3}  label={label}")
