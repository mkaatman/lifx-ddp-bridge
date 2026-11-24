#!/usr/bin/env python3
"""Prototype: spiral sweep around the chandelier, climbing one matrix row per lap.

A head rotates counter-clockwise (same direction as position numbering). On every tier
the bulb at the head's angle lights the current row on a few columns; after each lap the
row moves up (base -> tip), then repeats. Each candle repaints at most --fps (Set64).

Release the bulbs from the bridge first (WLED chandelier segments off).

  python3 spiral.py --lap 0.5 --secs 60
"""
import argparse, json, os, socket, struct, time

ap = argparse.ArgumentParser()
ap.add_argument("--secs", type=float, default=60)
ap.add_argument("--lap", type=float, default=0.5, help="seconds per revolution")
ap.add_argument("--cols", default="4,0,1", help="matrix columns to light per bulb")
ap.add_argument("--hold", type=float, default=0.04)
ap.add_argument("--fade", type=float, default=0.25, help="trail length (s)")
ap.add_argument("--fps", type=float, default=20)
ap.add_argument("--hue", type=float, default=230)
ap.add_argument("--bri", type=float, default=0.10, help="background brightness")
ap.add_argument("--tiers", default="1,2,3", help="which tiers run the spiral")
ap.add_argument("--tip", action="store_true", default=True, help="include the tip as the last lap")
a = ap.parse_args()
COLS = [int(c) for c in a.cols.split(",")]

HERE = os.path.dirname(os.path.abspath(__file__))
bulbs = json.load(open(os.path.join(HERE, "chandelier_bulbs.json")))["bulbs"]
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send(b, t, payload, copies=1):
    tgt = bytes.fromhex(b["target"].replace(":", "")) + b"\0\0"
    p = (struct.pack("<HHI", 36 + len(payload), 1024 | 0x1000, 0x53504952) + tgt + b"\0" * 6 +
         bytes([0, 0]) + struct.pack("<QHH", 0, t, 0) + payload)
    for _ in range(copies):
        sock.sendto(p, (b["ip"], 56700))


def paint(b, levels, dur_ms):
    w = b["matrix"][0]
    zs = b"".join(struct.pack("<HHHH", int(a.hue / 360 * 65535), int((1 - lv) * 65535),
                              int(min(1, a.bri + (1 - a.bri) * lv) * 65535), int(3500 + 3000 * lv))
                  for lv in levels)
    send(b, 715, bytes([0, 1, 0, 0, 0, w]) + struct.pack("<I", dur_ms) + zs + b"\0" * 8 * (64 - len(levels)))


def envelope(t):
    if t < 0: return 0.0
    if t < a.hold: return 1.0
    t -= a.hold
    return max(0.0, 1 - t / a.fade) ** 2 if t < a.fade else 0.0


tiers = {}
RUN = {int(t) for t in a.tiers.split(",")}
for b in bulbs:
    if b["tier"] in RUN:
        tiers.setdefault(b["tier"], []).append(b)
for t in tiers.values():
    t.sort(key=lambda b: b["pos"])
W, H = bulbs[0]["matrix"]
rows = list(range(H - 1, 0, -1)) + ([0] if a.tip else [])     # base row ... top body row, tip

cand = {b["ha_name"]: {"b": b, "sparks": [], "last": 0.0, "dirty": True, "n": W * H} for b in bulbs}
for c in cand.values():
    send(c["b"], 117, struct.pack("<HI", 65535, 0), copies=3)
    paint(c["b"], [0.0] * c["n"], 600)
time.sleep(0.8)

frame = 1 / a.fps
last_idx = {t: None for t in tiers}
sent = 0
t0 = time.time(); end = t0 + a.secs
while time.time() < end:
    now = time.time()
    rev = (now - t0) / a.lap
    row = rows[int(rev) % len(rows)]
    frac = rev % 1
    for tier, tb in tiers.items():
        idx = int(frac * len(tb))
        if (idx, row) != last_idx[tier]:
            last_idx[tier] = (idx, row)
            b = tb[idx]
            zones = [0] if row == 0 else [row * W + x for x in COLS]
            cand[b["ha_name"]]["sparks"] += [(z, now) for z in zones]
    for c in cand.values():
        if (not c["sparks"] and not c["dirty"]) or now - c["last"] < frame:
            continue
        lv = [0.0] * c["n"]
        alive = []
        for z, st in c["sparks"]:
            lv[z] = max(lv[z], envelope(now - st))
            if now - st < a.hold + a.fade:
                alive.append((z, st))
        c["sparks"] = alive
        paint(c["b"], lv, int(frame * 1000))
        c["dirty"] = bool(alive)
        c["last"] = now
        sent += 1
    time.sleep(0.002)
el = time.time() - t0
print(f"done: {el / a.lap:.0f} laps in {el:.0f}s, {sent} Set64 msgs ({sent / el:.0f}/s total, "
      f"{sent / el / len(cand):.1f}/s per candle avg)")
