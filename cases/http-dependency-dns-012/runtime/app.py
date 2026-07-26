#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CONFIG_PATH = Path("/etc/opsbench/app.json")
CONFIG_OVERLAY_PATH = Path("/var/lib/opsbench/app-config/current")
LOG_PATH = Path("/var/log/demo/app.log")
LEAKED_FILES: list[object] = []


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n")


def load_config() -> dict[str, object]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if CONFIG_OVERLAY_PATH.exists():
        overlay = json.loads(CONFIG_OVERLAY_PATH.read_text(encoding="utf-8"))
        config.update(overlay)
    return config


class Handler(BaseHTTPRequestHandler):
    server_version = "OpsBenchDemo/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        log(fmt % args)

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        config = load_config()
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "pid": os.getpid()})
            return
        if self.path == "/orders":
            self.handle_orders(config)
            return
        if self.path == "/checkout":
            if bool(config.get("feature_checkout_v2")):
                log("checkout v2 failed: unsupported pricing response")
                self.send_json(500, {"error": "checkout unavailable"})
            else:
                self.send_json(200, {"status": "accepted", "total": 4200})
            return
        if self.path == "/report-template":
            self.handle_report_template(config)
            return
        if self.path == "/report":
            self.handle_report()
            return
        if self.path == "/temp":
            self.handle_temp(config)
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/upload":
            self.send_json(404, {"error": "not found"})
            return
        config = load_config()
        length = int(self.headers.get("Content-Length", "0"))
        content = self.rfile.read(length) if length else b"opsbench-upload"
        directory = Path(str(config["upload_dir"]))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"upload-{time.time_ns()}.bin"
            path.write_bytes(content)
            self.send_json(201, {"stored": path.name, "bytes": len(content)})
        except OSError as exc:
            log(f"upload failed: {exc}")
            self.send_json(507, {"error": str(exc)})

    def handle_orders(self, config: dict[str, object]) -> None:
        host = str(config["dependency_host"])
        port = int(config["dependency_port"])
        timeout = float(config["dependency_timeout_ms"]) / 1000.0
        url = f"http://{host}:{port}/catalog"
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=timeout) as response:
                payload = json.loads(response.read().decode())
            catalog = payload["catalog"]
            items = payload["items"]
            if catalog != "ready" or type(items) is not int or items < 1:
                raise ValueError("catalog response failed schema validation")
            self.send_json(200, {"orders": 7, "catalog": catalog, "items": items})
        except (OSError, KeyError, ValueError, urllib.error.URLError) as exc:
            log(f"dependency request failed url={url} timeout={timeout}s error={exc}")
            self.send_json(502, {"error": "catalog dependency unavailable"})

    def handle_report_template(self, config: dict[str, object]) -> None:
        cache_scope = str(config.get("template_cache_scope", "request"))
        try:
            if cache_scope == "process":
                LEAKED_FILES.append(open("/opt/opsbench/runtime/fd-source.txt", "rb"))
            else:
                with open("/opt/opsbench/runtime/fd-source.txt", "rb") as handle:
                    handle.read(1)
            self.send_json(200, {"template": "standard"})
        except OSError as exc:
            log(f"report-template read failed: {exc}")
            self.send_json(503, {"error": str(exc)})

    def handle_report(self) -> None:
        try:
            with open("/run/report.lock", "a+", encoding="utf-8") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.send_json(200, {"report": "generated"})
        except BlockingIOError:
            log("report generation blocked by an existing file lock")
            self.send_json(503, {"error": "report busy"})

    def handle_temp(self, config: dict[str, object]) -> None:
        directory = Path(str(config["temp_dir"]))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / f"job-{time.time_ns()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            self.send_json(200, {"temporary_storage": "writable"})
        except OSError as exc:
            log(f"temporary file creation failed: {exc}")
            self.send_json(500, {"error": str(exc)})


def serve_http(config: dict[str, object]) -> ThreadingHTTPServer:
    bind = str(config["bind"])
    port = int(os.environ.get("APP_PORT", str(config["port"])))
    server = ThreadingHTTPServer((bind, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log(f"http server listening address={bind}:{port}")
    return server


def serve_https(config: dict[str, object]) -> ThreadingHTTPServer | None:
    if not bool(config.get("tls_enabled")):
        return None
    server = ThreadingHTTPServer((str(config["bind"]), int(config["tls_port"])), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(config["tls_cert"]), str(config["tls_key"]))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log(f"https server listening port={config['tls_port']}")
    return server


def main() -> int:
    try:
        config = load_config()
        servers = [serve_http(config), serve_https(config)]
    except Exception as exc:  # noqa: BLE001 - startup errors belong in the lab log.
        log(f"startup failed: {type(exc).__name__}: {exc}")
        print(f"startup failed: {exc}", file=sys.stderr)
        return 1
    while any(server is not None for server in servers):
        time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
