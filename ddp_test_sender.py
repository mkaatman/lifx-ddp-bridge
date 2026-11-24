#!/usr/bin/env python3
"""DDP test sender — stands in for WLED/LedFx while developing.

  ./ddp_test_sender.py solid 255 0 0              # all pixels red, one frame
  ./ddp_test_sender.py rainbow --fps 30 --secs 20  # rotating rainbow
  ./ddp_test_sender.py chase --pixels 21 --fps 20
"""
import argparse, colorsys, socket, struct, time

p = argparse.ArgumentParser()
p.add_argument("pattern", choices=["solid", "rainbow", "chase", "breathe"])
p.add_argument("rgb", nargs="*", type=int, default=[255, 255, 255])
p.add_argument("--host", default="192.168.2.143")
p.add_argument("--port", type=int, default=4048)
p.add_argument("--pixels", type=int, default=3)
p.add_argument("--fps", type=float, default=30)
p.add_argument("--secs", type=float, default=10)
p.add_argument("--speed", type=float, default=0.2, help="cycles per second")
a = p.parse_args()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
seq = 0


def send(pixels):
    global seq
    seq = seq % 15 + 1
    data = bytes(v for px in pixels for v in px)
    # flags: v1 + PUSH; seq; type RGB8 (0x0B); dest 1; offset 0; length
    hdr = struct.pack(">BBBBIH", 0x41, seq, 0x0B, 1, 0, len(data))
    sock.sendto(hdr + data, (a.host, a.port))


def frame(t):
    n = a.pixels
    if a.pattern == "solid":
        return [tuple(a.rgb)] * n
    if a.pattern == "rainbow":
        return [tuple(int(c * 255) for c in colorsys.hsv_to_rgb((t * a.speed + i / n) % 1, 1, 1)) for i in range(n)]
    if a.pattern == "chase":
        pos = int(t * a.speed * n) % n
        return [tuple(a.rgb) if i == pos else (0, 0, 0) for i in range(n)]
    if a.pattern == "breathe":
        import math
        k = (math.sin(t * a.speed * 2 * math.pi) + 1) / 2
        return [tuple(int(c * k) for c in a.rgb)] * n


if a.pattern == "solid":
    send(frame(0))
else:
    t0 = time.time()
    while (t := time.time() - t0) < a.secs:
        send(frame(t))
        time.sleep(1 / a.fps)
print("done")
