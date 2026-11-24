#!/usr/bin/env python3
"""Re-onboard LIFX bulbs that have fallen back to setup mode ("LIFX ..." soft APs).

Runs in WSL, drives a spare Windows Wi-Fi adapter via netsh.exe, and for each LIFX
setup network: join it -> identify bulb -> send SetAccessPoint over TLS -> leave.
Onboarding packet format from tserong/lifx-hacks onboard.py (vendor/lifx-hacks/).

Wi-Fi creds are read from a file (line 1 SSID, line 2 password) and never printed.

  python3 onboard_all.py --list              # just list LIFX setup networks
  python3 onboard_all.py --dry-run           # join first one, identify bulb + TLS handshake, send nothing
  python3 onboard_all.py                     # onboard all of them
  python3 onboard_all.py --only "LIFX Candle C 3A2CF"
"""
import argparse, datetime, json, os, re, socket, ssl, struct, subprocess, sys, tempfile, time

NETSH = "/mnt/c/Windows/System32/netsh.exe"
BULB_IP = "172.16.0.1"
SECURITY = {"open": 1, "wpa_tkip": 3, "wpa_aes": 4, "wpa2_aes": 5, "wpa2_tkip": 6, "wpa2_mixed": 7}

ap = argparse.ArgumentParser()
ap.add_argument("--iface", default="Wi-Fi", help="Windows Wi-Fi adapter to use (NOT \"Wi-Fi 2\" — Steam Frame dongle)")
ap.add_argument("--creds", default=os.path.expanduser("~/homeassistant/wifi.txt"))
ap.add_argument("--security", default="wpa2_aes", choices=SECURITY)
ap.add_argument("--list", action="store_true")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--only", action="append", default=[])
ap.add_argument("--rounds", type=int, default=3, help="rescan rounds to catch stragglers")
args = ap.parse_args()


def netsh(*a, check=False):
    r = subprocess.run([NETSH, *a], capture_output=True)
    out = r.stdout.decode("utf-8", "replace").replace("\r", "")
    if "location permission" in out:
        sys.exit("Windows is blocking Wi-Fi access: enable Settings > Privacy & security > Location > "
                 "'Let apps access your location' (and desktop apps).")
    if check and r.returncode:
        raise RuntimeError(f"netsh {' '.join(a)} failed: {out.strip()}")
    return out


def scan():
    # nudge a fresh scan by toggling a disconnect; results arrive in a few seconds
    netsh("wlan", "disconnect", f"interface={args.iface}")
    time.sleep(4)
    out = netsh("wlan", "show", "networks", f"interface={args.iface}", "mode=bssid")
    nets, ssid = {}, None
    for line in out.splitlines():
        m = re.match(r"^SSID \d+ : (.*)$", line)
        if m:
            ssid = m.group(1).strip()
        m = re.match(r"^\s+Signal\s+: (\d+)%", line)
        if m and ssid and ssid.upper().startswith("LIFX"):
            nets[ssid] = max(nets.get(ssid, 0), int(m.group(1)))
    return nets


def win_temp_dir():
    w = subprocess.run(["cmd.exe", "/c", "echo %TEMP%"], capture_output=True, cwd="/mnt/c").stdout.decode().strip()
    return subprocess.run(["wslpath", w], capture_output=True).stdout.decode().strip(), w


def connect(ssid):
    hexname = ssid.encode().hex().upper()
    xml = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{ssid}</name>
  <SSIDConfig><SSID><hex>{hexname}</hex><name>{ssid}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType><connectionMode>manual</connectionMode>
  <MSM><security><authEncryption><authentication>open</authentication>
  <encryption>none</encryption><useOneX>false</useOneX></authEncryption></security></MSM>
</WLANProfile>"""
    linux_tmp, win_tmp = win_temp_dir()
    fn = f"lifx_onboard_{hexname[:16]}.xml"
    with open(os.path.join(linux_tmp, fn), "w") as f:
        f.write(xml)
    netsh("wlan", "add", "profile", f"filename={win_tmp}\\{fn}", f"interface={args.iface}", "user=current", check=True)
    os.remove(os.path.join(linux_tmp, fn))
    netsh("wlan", "connect", f"name={ssid}", f"ssid={ssid}", f"interface={args.iface}", check=True)
    for _ in range(30):  # wait for association + DHCP
        time.sleep(1)
        st = netsh("wlan", "show", "interfaces")
        block = st.split(f"Name                   : {args.iface}")[-1].split("\n\n")[0]
        if re.search(r"State\s+: connected", block) and ssid in block:
            if probe_udp() is not None:
                return True
    return False


def forget(ssid):
    netsh("wlan", "disconnect", f"interface={args.iface}")
    netsh("wlan", "delete", "profile", f"name={ssid}", f"interface={args.iface}")


def probe_udp():
    """GetService -> returns bulb target MAC, or None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.7)
    pkt = struct.pack("<HHI", 36, 1024 | 0x3000, 0x4F4E4231) + b"\0" * 14 + bytes([1, 1]) + struct.pack("<QHH", 0, 2, 0)
    for _ in range(3):
        try:
            s.sendto(pkt, (BULB_IP, 56700))
            d, _ = s.recvfrom(1024)
            if struct.unpack_from("<H", d, 32)[0] == 3:
                return d[8:14].hex(":")
        except OSError:
            pass
    return None


def tls_socket():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1      # bulbs speak old TLS
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    sock = ctx.wrap_socket(socket.create_connection((BULB_IP, 56700), timeout=8))
    return sock


def onboard_packet(ssid, pw):
    # header: size=134, protocol 1024|addressable|tagged, type 305 SetAccessPoint
    p = bytes.fromhex("86000034") + b"\0" * 28 + struct.pack("<HH", 305, 0)
    p += bytes([2])                                  # interface: 2 = station
    p += ssid.encode()[:32].ljust(32, b"\0")
    p += pw.encode()[:64].ljust(64, b"\0")
    p += bytes([SECURITY[args.security]])
    assert len(p) == 134
    return p


def log_onboard(ssid, mac):
    """Append setup-AP -> bulb MAC to onboard_log.json (for restore_labels.py / history)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "onboard_log.json")
    log = json.load(open(path)) if os.path.exists(path) else []
    log.append({"when": datetime.datetime.now().isoformat(timespec="seconds"), "setup_ssid": ssid, "target": mac})
    json.dump(log, open(path, "w"), indent=1)


def main():
    if not os.path.exists(NETSH):
        sys.exit("netsh.exe not found — run this from WSL")
    lines = open(args.creds).read().splitlines()
    home_ssid, home_pw = lines[0].strip(), lines[1].rstrip("\n")

    done, failed = {}, {}
    for rnd in range(1 if (args.list or args.dry_run) else args.rounds):
        nets = scan()
        if args.only:
            nets = {k: v for k, v in nets.items() if k in args.only}
        todo = [s for s in sorted(nets, key=lambda k: -nets[k]) if s not in done]
        print(f"\nround {rnd + 1}: {len(nets)} LIFX setup networks visible, {len(todo)} to do")
        for s in todo:
            print(f"  {s}  ({nets[s]}%)")
        if args.list:
            return
        if not todo:
            break
        for ssid in todo:
            print(f"\n→ {ssid}")
            try:
                if not connect(ssid):
                    print("   could not join / bulb not answering"); failed[ssid] = "join"; continue
                mac = probe_udp()
                print(f"   joined; bulb target {mac}")
                sock = tls_socket()
                print(f"   TLS ok ({sock.version()})")
                if args.dry_run:
                    sock.close(); print("   dry run — nothing sent"); done[ssid] = mac; return
                sock.sendall(onboard_packet(home_ssid, home_pw))
                time.sleep(1.5)
                sock.close()
                print(f"   sent SetAccessPoint ({args.security})")
                done[ssid] = mac
                log_onboard(ssid, mac)
            except Exception as e:
                print(f"   ERROR: {e}"); failed[ssid] = str(e)
            finally:
                forget(ssid)
    print(f"\nonboarded {len(done)}: {done}")
    if failed:
        print(f"failed {len(failed)}: {failed}")
    print("Give them ~60s, then: python3 lifx_inventory.py --write")


main()
