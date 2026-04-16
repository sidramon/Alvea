"""
Alvea — HTTP server.

Routes:
    GET  /                      → index.html
    GET  /static/<file>         → static files
    GET  /api/status?since=N    → JSON snapshot (events from offset N)
    POST /api/run               → start agent loop (JSON config body)
    POST /api/stop              → stop agent loop
    POST /api/reset             → reset all state
"""

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from web import runner

PORT = 5000
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ─────────────────────────────────────────────────────────────
# REQUEST HANDLER
# ─────────────────────────────────────────────────────────────

class AlveaHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # silence access logs
        pass

    # ── GET ──────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path

        if path in ("/", "/index.html"):
            self._serve_static("index.html", "text/html; charset=utf-8")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path == "/api/status":
            qs    = parse_qs(parsed.query)
            since = int(qs.get("since", ["0"])[0])
            self._json(runner.state.get_snapshot(since))
        else:
            self._send(404, b"Not found")

    # ── POST ─────────────────────────────────────────────────

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/run":
            try:
                config = json.loads(body)
                runner.start_run(config)
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)

        elif path == "/api/stop":
            runner.stop_run()
            self._json({"ok": True})

        elif path == "/api/reset":
            runner.reset()
            self._json({"ok": True})

        else:
            self._send(404, b"Not found")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ── Helpers ──────────────────────────────────────────────

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, filename: str, content_type: str = None):
        filepath = os.path.join(STATIC_DIR, filename)
        if not os.path.isfile(filepath):
            self._send(404, b"Not found")
            return
        mime = content_type or mimetypes.guess_type(filepath)[0] or "application/octet-stream"
        with open(filepath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def start_server(port: int = PORT):
    server = ThreadingHTTPServer(("", port), AlveaHandler)
    print(f"[ALVEA] Interface web → http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ALVEA] Serveur arrêté.")
