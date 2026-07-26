#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CONFIG = Path("/etc/opsbench/dependency.json")
LOG = Path("/var/log/demo/dependency.log")


def log(message: str) -> None:
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        log(fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        time.sleep(float(config.get("delay_ms", 0)) / 1000.0)
        status = int(config.get("status", 200))
        try:
            body = Path(str(config["data_file"])).read_bytes()
        except OSError as exc:
            status = 500
            body = b'{"error":"catalog storage unavailable"}'
            log(f"catalog storage read failed: {exc}")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


port = int(os.environ.get("CATALOG_PORT", "9001"))
log(f"catalog server listening address=0.0.0.0:{port}")
ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
