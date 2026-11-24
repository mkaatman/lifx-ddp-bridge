#!/usr/bin/env python3
"""Position test patterns for the chandelier (direct LIFX LAN, uses chandelier_bulbs.json).

  python3 chandelier_test.py rainbow            # every tier: pos1 white, then rainbow in position order
  python3 chandelier_test.py rainbow --tier 3
  python3 chandelier_test.py flash Tier3Bulb4   # blink one bulb, others dim
  python3 chandelier_test.py warm               # restore all to warm white
"""
import argparse, colorsys, json, os, socket, struct, time

HERE = os.path.dirname(os.path.abspath(__file__))
inv = json.load(open(os.path.join(HERE, "chandelier_bulbs.json")))["bulbs"]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send(b, t, payload):
    tgt = bytes.fromhex(b["target"].replace(":", "")) + b"\0\0"
    p = (struct.pack("<HHI", 36 + len(payload), 1024 | 0x1000, 0x54455354) + tgt + b"\0" * 6 +
         bytes([0, 0]) + struct.pack("<QHH", 0, t, 0) + payload)
    for _ in range(2):           # no acks; send twice for UDP loss
        s.sendto(p, (b["ip"], 56700))


def color(b, h, sat, bri, k=3500, ms=300):
    send(b, 117, struct.pack("<HI", 65535, 0))                                   # power on
    send(b, 102, struct.pack("<BHHHHI", 0, int(h % 360 / 360 * 65535), int(sat * 65535), int(bri * 65535), k, ms))


ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["rainbow", "flash", "warm"])
ap.add_argument("name", nargs="?")
ap.add_argument("--tier", type=int)
a = ap.parse_args()

if a.mode == "rainbow":
    for tier in sorted({b["tier"] for b in inv}):
        if a.tier and tier != a.tier:
            continue
        bulbs = sorted([b for b in inv if b["tier"] == tier], key=lambda b: b["pos"])
        n = len(bulbs)
        for i, b in enumerate(bulbs):
            if i == 0:
                color(b, 0, 0, 1.0, 5000)                                         # white marker
            else:
                color(b, (i - 1) * 300 / max(1, n - 2), 1, 0.8)                   # red -> magenta
        print(f"tier {tier}: " + ", ".join(f"{b['pos']}" for b in bulbs))
elif a.mode == "flash":
    target = [b for b in inv if b["ha_name"] == a.name]
    for b in inv:
        color(b, 0, 0, 0.05, 2700)
    for _ in range(6):
        for b in target: color(b, 120, 1, 1, ms=0)
        time.sleep(0.5)
        for b in target: color(b, 0, 0, 0.05, 2700, ms=0)
        time.sleep(0.5)
    for b in target: color(b, 120, 1, 1, ms=0)
elif a.mode == "warm":
    for b in inv:
        color(b, 0, 0, 0.6, 2700, 1000)
