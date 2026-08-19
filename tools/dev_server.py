#!/usr/bin/env python3
"""Serve the RUMI portal locally so the real UI can be driven in a browser.

Python 3.13 removed CGIHTTPRequestHandler, and the portal is a CGI script, so
this runs `api.cgi` as a subprocess with the CGI environment filled in and
serves everything else as static files. It exists to catch problems before a
release reaches the live site, not to be a production server.

    python3 tools/dev_server.py --port 8765 --data-dir /tmp/rumi-dev

Then open http://127.0.0.1:8765/
"""
import argparse
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "portal"
API = PORTAL / "api.cgi"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".nc": "application/x-netcdf",
    ".py": "text/x-python",
}


class PortalHandler(BaseHTTPRequestHandler):
    data_dir = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("dev_server: " + fmt % args + "\n")

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_DELETE(self):
        self.handle_request("DELETE")

    def do_PUT(self):
        self.handle_request("PUT")

    def handle_request(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.lstrip("/") or "index.html"
        if path == "api.cgi":
            self.run_cgi(method, parsed.query)
            return
        target = (PORTAL / path).resolve()
        try:
            target.relative_to(PORTAL)
        except ValueError:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def run_cgi(self, method, query):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        env = dict(os.environ)
        env.update(
            {
                "REQUEST_METHOD": method,
                "QUERY_STRING": query,
                "SCRIPT_NAME": "/api.cgi",
                "CONTENT_LENGTH": str(length),
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "HTTP_COOKIE": self.headers.get("Cookie", ""),
                "REMOTE_ADDR": self.client_address[0],
                "SERVER_NAME": "127.0.0.1",
                "SERVER_PORT": str(self.server.server_address[1]),
                "RUMI_PORTAL_DATA_DIR": self.data_dir,
            }
        )
        for header, value in self.headers.items():
            key = "HTTP_" + header.upper().replace("-", "_")
            env.setdefault(key, value)

        proc = subprocess.run(
            [sys.executable, str(API)],
            input=body,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(PORTAL),
        )
        if proc.stderr:
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))

        raw = proc.stdout
        head, _, payload = raw.partition(b"\r\n\r\n")
        if not _:
            head, _, payload = raw.partition(b"\n\n")
        status = 200
        headers = []
        for line in head.decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            name, _, value = line.partition(":")
            name, value = name.strip(), value.strip()
            if name.lower() == "status":
                status = int(value.split()[0])
            else:
                headers.append((name, value))

        self.send_response(status)
        sent_length = False
        for name, value in headers:
            # The dev server is plain HTTP, so a Secure cookie would be dropped.
            if name.lower() == "set-cookie":
                value = "; ".join(
                    part for part in value.split("; ") if part.strip() != "Secure"
                )
            if name.lower() == "content-length":
                sent_length = True
                value = str(len(payload))
            self.send_header(name, value)
        if not sent_length:
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description="Local RUMI portal dev server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="/tmp/rumi-dev")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    PortalHandler.data_dir = str(data_dir)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), PortalHandler)
    print(f"RUMI dev server on http://127.0.0.1:{args.port}/  data={data_dir}")
    server.serve_forever()


if __name__ == "__main__":
    main()
