#!/usr/bin/env python3
"""Prototype: dark-blue candles with random individual zones flashing white ("starfield").

Each event flashes 1..N random zones (anywhere on the chandelier), each starting after a
random offset so flashes may or may not overlap. Fades are rendered here (per-zone
envelopes) and each busy candle is repainted at up to --fps with Set64, so overlapping
flashes on the same candle don't cut each other off.

Release the bulbs from the bridge first (switch the WLED chandelier segments off).

  python3 sparkle.py --secs 120 --rate 6 --max-zones 3
"""
import argparse, json, os, random, socket, struct, time

ap = argparse.ArgumentParser()
ap.add_argument("--secs", type=float, default=120)
ap.add_argument("--rate", type=float, default=6, help="flash events per second (chandelier-wide)")
ap.add_argument("--min-zones", type=int, default=1)
ap.add_argument("--max-zones", type=int, default=3)
ap.add_argument("--spread", type=float, default=0.3, help="max random start offset per zone (s)")
ap.add_argument("--hold", type=float, default=0.05, help="seconds at full white")
ap.add_argument("--fade", type=float, default=0.35, help="seconds to fade back to blue")
ap.add_argument("--fps", type=float, default=20, help="max repaint rate per candle")
ap.add_argument("--streak", type=float, default=0.4, help="probability a flash is a rising streak up one column")
ap.add_argument("--step", type=float, default=0.06, help="seconds between rows in a streak")
ap.add_argument("--hue", type=float, default=230)
ap.add_argument("--bri", type=float, default=0.15, help="background blue brightness 0..1")
a = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
bulbs = json.load(open(os.path.join(HERE, "chandelier_bulbs.json")))["bulbs"]
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
BG = (a.hue, 1.0, a.bri)


def send(b, t, payload, copies=1):
    tgt = bytes.fromhex(b["target"].replace(":", "")) + b"\0\0"
    p = (struct.pack("<HHI", 36 + len(payload), 1024 | 0x1000, 0x53504B32) + tgt + b"\0" * 6 +
         bytes([0, 0]) + struct.pack("<QHH", 0, t, 0) + payload)
    for _ in range(copies):
        sock.sendto(p, (b["ip"], 56700))


def hsbk(h, s, v, k):
    return struct.pack("<HHHH", int(h / 360 * 65535) % 65536, int(s * 65535), int(min(1, v) * 65535), k)


def paint(b, levels, dur_ms):
    """levels[z] = white amount 0..1 blended over the blue background."""
    w = b["matrix"][0]
    zs = b""
    for lv in levels:
        # blend: saturation drops and brightness rises toward white as lv -> 1
        zs += hsbk(BG[0], BG[1] * (1 - lv), BG[2] + (1 - BG[2]) * lv, int(3500 + 3000 * lv))
    payload = bytes([0, 1, 0, 0, 0, w]) + struct.pack("<I", dur_ms) + zs + b"\0" * 8 * (64 - len(levels))
    send(b, 715, payload)


def real_zones(b):
    w, h = b["matrix"]
    return [0] + [y * w + x for y in range(1, h) for x in range(w)]   # row 0 = tip, one zone


def envelope(t):
    if t < 0: return 0.0
    if t < a.hold: return 1.0
    t -= a.hold
    return max(0.0, 1 - t / a.fade) ** 2 if t < a.fade else 0.0


cands = [{"b": b, "zones": real_zones(b), "sparks": [], "last": 0.0, "dirty": True,
          "n": b["matrix"][0] * b["matrix"][1]} for b in bulbs]
for c in cands:
    send(c["b"], 117, struct.pack("<HI", 65535, 0), copies=3)
    paint(c["b"], [0.0] * c["n"], 800)
time.sleep(1)

frame = 1 / a.fps
sent = flashes = 0
t0 = time.time(); end = t0 + a.secs
next_event = t0
while time.time() < end:
    now = time.time()
    while now >= next_event:                           # schedule an event: 1..N zones, staggered
        for _ in range(random.randint(a.min_zones, a.max_zones)):
            c = random.choice(cands)
            start = next_event + random.uniform(0, a.spread)
            if random.random() < a.streak:             # rising streak: base row -> tip
                w, h = c["b"]["matrix"]
                x = random.randrange(w)
                for i, y in enumerate(range(h - 1, 0, -1)):
                    c["sparks"].append((y * w + x, start + i * a.step))
                c["sparks"].append((0, start + (h - 1) * a.step))   # tip zone
            else:
                c["sparks"].append((random.choice(c["zones"]), start))
            flashes += 1
        next_event += random.expovariate(a.rate)
    for c in cands:
        if not c["sparks"] and not c["dirty"]:
            continue
        if now - c["last"] < frame:
            continue
        lv = [0.0] * c["n"]
        alive = []
        for z, start in c["sparks"]:
            e = envelope(now - start)   # 0 before its start time
            lv[z] = max(lv[z], e)
            if now - start < a.hold + a.fade or now < start:
                alive.append((z, start))
        c["sparks"] = alive
        paint(c["b"], lv, int(frame * 1000))
        c["dirty"] = bool(alive)                       # one final paint after the last spark ends
        c["last"] = now
        sent += 1
    time.sleep(0.004)
el = time.time() - t0
print(f"done: {flashes} zone flashes in {el:.0f}s ({flashes/el:.1f}/s), {sent} Set64 msgs ({sent/el:.0f}/s total, "
      f"{sent/el/len(cands):.1f}/s per candle avg)")
