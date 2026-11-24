#!/usr/bin/env python3
"""Scan a /24 for LIFX bulbs, query product/firmware/matrix size, match to chandelier_bulbs.json.

  python3 lifx_inventory.py [subnet-prefix] [--write]
--write fills ip/target/product/matrix into chandelier_bulbs.json.
"""
import json, os, socket, struct, sys, time

SUBNET = next((a for a in sys.argv[1:] if not a.startswith("--")), "192.168.2")
WRITE = "--write" in sys.argv
PORT, SOURCE = 56700, 0x4C494659
HERE = os.path.dirname(os.path.abspath(__file__))

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("", 0))
seq = 0


def pkt(t, target=b"\0" * 8, tagged=True):
    global seq
    seq = (seq + 1) & 0xFF
    proto = 1024 | 0x1000 | (0x2000 if tagged else 0)
    return (struct.pack("<HHI", 36, proto, SOURCE) + target + b"\0" * 6 +
            bytes([1, seq]) + struct.pack("<QHH", 0, t, 0))


def ask(ip, target, t, want, tries=4, timeout=0.5):
    for _ in range(tries):
        s.sendto(pkt(t, target, False), (ip, PORT))
        end = time.time() + timeout
        while time.time() < end:
            s.settimeout(max(0.01, end - time.time()))
            try:
                d, (rip, _) = s.recvfrom(2048)
            except socket.timeout:
                break
            if rip == ip and struct.unpack_from("<H", d, 32)[0] == want:
                return d
    return None


# 1. discover via unicast sweep (WSL NAT blocks broadcast)
found = {}
s.settimeout(0.2)
for rnd in range(3):
    for i in range(1, 255):
        s.sendto(pkt(2), (f"{SUBNET}.{i}", PORT))
        time.sleep(0.002)
    end = time.time() + 2
    while time.time() < end:
        try:
            d, (ip, _) = s.recvfrom(2048)
        except socket.timeout:
            continue
        if len(d) >= 36 and struct.unpack_from("<H", d, 32)[0] == 3:
            found[ip] = d[8:16]

# 2. details
mac = lambda b: ":".join(f"{x:02x}" for x in b[:6])
rows = []
for ip, tgt in sorted(found.items(), key=lambda kv: int(kv[0].rsplit(".", 1)[1])):
    r = {"ip": ip, "target": mac(tgt)}
    d = ask(ip, tgt, 101, 107)                                   # GetColor -> LightState
    if d:
        r["label"] = d[48:80].split(b"\0")[0].decode(errors="replace")
        r["power"] = struct.unpack_from("<H", d, 46)[0] > 0
    d = ask(ip, tgt, 32, 33)                                     # GetVersion -> StateVersion
    if d:
        r["product"] = struct.unpack_from("<I", d, 40)[0]
    d = ask(ip, tgt, 14, 15)                                     # GetHostFirmware
    if d:
        mn, mj = struct.unpack_from("<HH", d, 36 + 16)
        r["fw"] = f"{mj}.{mn}"
    d = ask(ip, tgt, 701, 702, tries=2)                          # GetDeviceChain -> StateDeviceChain
    if d and len(d) >= 36 + 1 + 55:
        w, h = d[36 + 1 + 16], d[36 + 1 + 17]
        r["matrix"] = [w, h]
    rows.append(r)

# 3. match to inventory
inv_path = os.path.join(HERE, "chandelier_bulbs.json")
inv = json.load(open(inv_path))
by_mac = {}
for b in inv["bulbs"]:
    m = int(b["wifi_mac"].replace(":", ""), 16)
    by_mac[m] = b
    by_mac[m - 1] = b
matched = set()
for r in rows:
    b = by_mac.get(int(r["target"].replace(":", ""), 16))
    r["inv"] = b
    if b:
        matched.add(b["wifi_mac"])
        if WRITE:
            b.update(ip=r["ip"], target=r["target"], product=r.get("product"),
                     fw=r.get("fw"), matrix=r.get("matrix"), lan_label=r.get("label"))

print(f"{len(rows)} LIFX devices found\n")
for r in rows:
    b = r["inv"]
    where = f"T{b['tier']}P{b['pos']}" if b and b["tier"] else ("chandelier?" if b else "")
    print(f"{r['ip']:15} {r['target']}  {r.get('label', '?'):26} prod={r.get('product', '?'):<4} "
          f"fw={r.get('fw', '?'):6} matrix={r.get('matrix', '-')!s:8} {'on' if r.get('power') else 'off'}  {where}")
missing = [b for b in inv["bulbs"] if b["wifi_mac"] not in matched]
print(f"\nchandelier matched {21 - len(missing)}/21")
for b in missing:
    print("  MISSING:", b["ha_name"], b["wifi_mac"])
if WRITE:
    json.dump(inv, open(inv_path, "w"), indent=1)
    print("wrote", inv_path)
