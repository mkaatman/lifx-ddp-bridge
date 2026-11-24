#!/usr/bin/env python3
"""Restore LIFX bulb labels from chandelier_bulbs.json (the MAC-keyed source of truth).

Finds bulbs on the LAN, matches them by MAC (LIFX target, or wifi MAC - 1), and
reports/fixes any whose on-bulb label differs from the saved one.

  python3 restore_labels.py            # report only
  python3 restore_labels.py --apply    # send SetLabel to mismatched bulbs
"""
import json, os, socket, struct, sys, time

SUBNET = next((a for a in sys.argv[1:] if not a.startswith("--")), "192.168.2")
APPLY = "--apply" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
PORT, SOURCE = 56700, 0x4C42454C

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("", 0))


def pkt(t, target=b"\0" * 8, payload=b"", tagged=False, ack=False, res=True):
    proto = 1024 | 0x1000 | (0x2000 if tagged else 0)
    flags = (1 if res else 0) | (2 if ack else 0)
    return (struct.pack("<HHI", 36 + len(payload), proto, SOURCE) + target + b"\0" * 6 +
            bytes([flags, 0]) + struct.pack("<QHH", 0, t, 0) + payload)


def ask(ip, target, t, want, payload=b"", tries=4, ack=False):
    for _ in range(tries):
        s.sendto(pkt(t, target, payload, ack=ack, res=not ack), (ip, PORT))
        end = time.time() + 0.5
        while time.time() < end:
            s.settimeout(max(0.01, end - time.time()))
            try:
                d, (rip, _) = s.recvfrom(2048)
            except socket.timeout:
                break
            if rip == ip and struct.unpack_from("<H", d, 32)[0] == want:
                return d
    return None


inv = json.load(open(os.path.join(HERE, "chandelier_bulbs.json")))
wanted = {}
for b in inv["bulbs"]:
    if not b.get("ha_name", "").startswith("Tier"):
        continue                                   # unverified / unnamed — skip
    m = int(b["wifi_mac"].replace(":", ""), 16)
    wanted[m] = wanted[m - 1] = b

found = {}
s.settimeout(0.2)
for _ in range(3):
    for i in range(1, 255):
        s.sendto(pkt(2, tagged=True), (f"{SUBNET}.{i}", PORT))
        time.sleep(0.002)
    end = time.time() + 2
    while time.time() < end:
        try:
            d, (ip, _) = s.recvfrom(2048)
        except socket.timeout:
            continue
        if struct.unpack_from("<H", d, 32)[0] == 3:
            found[ip] = d[8:16]

fixed = ok = 0
for ip, tgt in sorted(found.items()):
    b = wanted.get(int.from_bytes(tgt[:6], "big"))
    if not b:
        continue
    d = ask(ip, tgt, 23, 25)                       # GetLabel -> StateLabel
    cur = d[36:68].split(b"\0")[0].decode(errors="replace") if d else "?"
    want = b["ha_name"]
    if cur == want:
        ok += 1
        continue
    print(f"{ip:15} {tgt[:6].hex(':')}  label '{cur}' -> '{want}'", end="")
    if APPLY:
        ask(ip, tgt, 24, 45, want.encode()[:32].ljust(32, b"\0"), ack=True)   # SetLabel, wait for Acknowledgement
        d = ask(ip, tgt, 23, 25)
        new = d[36:68].split(b"\0")[0].decode(errors="replace") if d else "?"
        print("  ✓" if new == want else f"  ✗ (now '{new}')")
        fixed += new == want
    else:
        print("  (dry run)")
print(f"\n{len(found)} LIFX on LAN · {ok} labels already correct · "
      f"{fixed if APPLY else 'n/a'} fixed · {len(set(map(id, wanted.values())))} named bulbs in inventory")
