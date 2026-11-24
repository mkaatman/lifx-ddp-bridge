"""Tiny stdlib-only Home Assistant WebSocket client (no third-party deps)."""
import base64, json, os, socket, struct

TOKEN_FILE = os.path.expanduser("~/homeassistant/token.txt")


class HA:
    def __init__(self, host="192.168.2.20", port=8123):
        self.s = socket.create_connection((host, port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /api/websocket HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.s.recv(4096)
        if b" 101 " not in resp.split(b"\r\n")[0]:
            raise RuntimeError(resp.split(b"\r\n")[0])
        self.buf = resp.split(b"\r\n\r\n", 1)[1]
        self.id = 0
        assert self._recv()["type"] == "auth_required"
        self._send({"type": "auth", "access_token": open(TOKEN_FILE).read().strip()})
        r = self._recv()
        if r["type"] != "auth_ok":
            raise RuntimeError("auth failed")

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _recv(self):
        data = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data += self._read(n)
            if b0 & 0x80:
                return json.loads(data)

    def _send(self, obj):
        payload = json.dumps(obj).encode()
        mask = os.urandom(4)
        n = len(payload)
        hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                               bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                               bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def call(self, type_, **kw):
        self.id += 1
        self._send({"id": self.id, "type": type_, **kw})
        while True:
            r = self._recv()
            if r.get("id") == self.id and r.get("type") == "result":
                if not r["success"]:
                    raise RuntimeError(f"{type_}: {r.get('error')}")
                return r["result"]
