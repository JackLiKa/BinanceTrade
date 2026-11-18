#!/usr/bin/env python3
"""Tiny Google OAuth relay for the Tokyo node (stdlib only).

The Guangzhou panel cannot reach Google (TLS reset), but the Tokyo node can.
This process listens only on the WireGuard address and forwards exactly three
fixed Google endpoints; it is not a general-purpose proxy.

Environment:
    RELAY_BIND=10.66.0.2      # WireGuard address
    RELAY_PORT=8101
    RELAY_TOKEN=...           # optional shared header X-Relay-Token
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
TOKEN = os.environ.get("RELAY_TOKEN", "").strip()
CTX = ssl.create_default_context()


class Handler(BaseHTTPRequestHandler):
    server_version = "gridtrade-google-relay/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return not TOKEN or self.headers.get("X-Relay-Token", "") == TOKEN

    def _forward(self, method: str, url: str, body: bytes | None, headers: dict[str, str]) -> None:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15, context=CTX) as response:
                self._send(response.status, response.read(), response.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as error:
            self._send(error.code, error.read(), error.headers.get("Content-Type", "application/json"))
        except Exception as error:  # noqa: BLE001 - return relay failure as JSON
            self._send(502, json.dumps({"error": "relay_failed", "detail": str(error)}).encode())

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(403, b'{"error":"forbidden"}')
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        if self.path.rstrip("/") == "/device/code":
            self._forward("POST", DEVICE_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
        elif self.path.rstrip("/") == "/token":
            self._forward("POST", TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
        else:
            self._send(404, b'{"error":"not_found"}')

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(403, b'{"error":"forbidden"}')
            return
        if self.path.rstrip("/") == "/healthz":
            self._send(200, b'{"ok":true}')
            return
        if self.path.rstrip("/") == "/userinfo":
            auth = self.headers.get("Authorization", "")
            self._forward("GET", USERINFO_URL, None, {"Authorization": auth})
            return
        self._send(404, b'{"error":"not_found"}')


def main() -> None:
    bind = os.environ.get("RELAY_BIND", "10.66.0.2")
    port = int(os.environ.get("RELAY_PORT", "8101"))
    ThreadingHTTPServer((bind, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
