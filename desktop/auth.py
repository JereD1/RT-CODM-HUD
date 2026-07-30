import http.server
import socketserver
import threading
import webbrowser
import json
import time
import requests
from urllib.parse import urlparse, parse_qs

from config import WEB_BASE_URL, AUTH_START_PATH, EXCHANGE_URL, SESSION_FILE


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/callback":
            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            _CallbackHandler.result["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Connected. You can close this tab.</body></html>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silence default request logging


def sign_in(timeout_seconds: int = 180) -> dict:
    """Opens the system browser to sign in via Clerk, waits for the
    one-time code on a local loopback server, exchanges it for the
    signed-in user's identity. Returns {"userId": ..., "orgId": ...} and
    caches it to disk.

    Raises TimeoutError if sign-in isn't completed in time, RuntimeError
    if the exchange fails.
    """
    _CallbackHandler.result = {}
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _CallbackHandler)
    port = httpd.server_address[1]

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        auth_url = f"{WEB_BASE_URL}{AUTH_START_PATH}?port={port}"
        webbrowser.open(auth_url)

        waited = 0.0
        while "code" not in _CallbackHandler.result and waited < timeout_seconds:
            time.sleep(0.25)
            waited += 0.25

        if "code" not in _CallbackHandler.result:
            raise TimeoutError("Sign-in timed out — no response from the browser.")

        code = _CallbackHandler.result["code"]
        if not code:
            raise RuntimeError("Browser callback didn't include a code.")

        resp = requests.post(EXCHANGE_URL, json={"code": code}, timeout=10)
        if not resp.ok:
            raise RuntimeError(f"Failed to exchange code: {resp.status_code} {resp.text}")

        identity = resp.json()  # {"userId": ..., "orgId": ...}
        SESSION_FILE.write_text(json.dumps(identity))
        return identity
    finally:
        httpd.shutdown()
        httpd.server_close()


def load_cached_identity() -> dict | None:
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            return None
    return None


def sign_out():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def compute_broadcast_id(identity: dict, production_id: str | None = None) -> str:
    """Personal channel only, by design — see the Team Mode note in chat.
    This deliberately ignores identity['orgId'] rather than silently going
    org-scoped whenever the signed-in browser session happens to have an
    org active, which was the exact ambient-vs-explicit Team Mode bug
    already fixed once on the web side. If/when this app gets a real Team
    Mode toggle, wire orgId in here explicitly, opt-in only."""
    base = identity["userId"]
    return f"{base}-{production_id}" if production_id else base