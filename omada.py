"""Minimal read-only Omada controller client (stdlib). Creds: ~/homeassistant/omada.txt (user, pass)."""
import http.cookiejar, json, os, ssl, urllib.request

BASE = "https://192.168.2.1:7443"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


class Omada:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX),
                                              urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.cid = self._raw("GET", "/api/info")["result"]["omadacId"]
        user, pw = open(os.path.expanduser("~/homeassistant/omada.txt")).read().splitlines()[:2]
        r = self._raw("POST", f"/{self.cid}/api/v2/login", {"username": user, "password": pw})
        if r.get("errorCode") != 0:
            raise RuntimeError(f"login failed: {r.get('msg')}")
        self.token = r["result"]["token"]

    def _raw(self, method, path, body=None, headers=None):
        req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        return json.loads(self.op.open(req, timeout=20).read())

    def get(self, path):
        r = self._raw("GET", f"/{self.cid}/api/v2{path}", headers={"Csrf-Token": self.token})
        if r.get("errorCode") != 0:
            raise RuntimeError(f"{path}: {r.get('errorCode')} {r.get('msg')}")
        return r["result"]
