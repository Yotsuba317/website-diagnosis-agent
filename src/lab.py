"""Isolated fault injection on localhost, plus explicitly labelled synthetic cases."""

import json
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent import ROOT
from .tools import Probes, RecordedProbes, parse_target, utc_now


def load_cases():
    return json.loads((ROOT / "data/cases.json").read_text(encoding="utf-8"))


@contextmanager
def laboratory(case):
    fault = case["fault"]
    if fault in ("dns_failure", "insufficient_evidence"):
        target = parse_target("http://fixture.test/")
        common = {"source": "synthetic_fixture", "observed_at": utc_now(),
                  "vantage_point": "explicit synthetic teaching fixture"}
        if fault == "dns_failure":
            records = {"check_dns": {**common, "status": "error", "error_type": "dns_resolution_failed",
                                      "detail": "Simulated NXDOMAIN", "elapsed_ms": 12}}
        else:
            records = {"check_dns": {**common, "status": "ok", "addresses": ["192.0.2.10"], "elapsed_ms": 5},
                       "check_tcp": {**common, "status": "ok", "port": 80, "elapsed_ms": 6},
                       "check_http": {**common, "status": "unavailable", "detail": "HTTP probe observation missing"}}
        yield RecordedProbes(target, records)
        return
    if fault == "tcp_failure":
        # Reserve an ephemeral local port without listening, preventing reuse by the lab.
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            yield Probes(f"http://127.0.0.1:{reserved.getsockname()[1]}/", timeout=1.5)
        return

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if fault == "slow_response":
                time.sleep(1.2)
            self.send_response(503 if fault == "http_error" else 200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            try:
                self.wfile.write(b"OK")
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        scheme = "https" if fault == "tls_failure" else "http"
        yield Probes(f"{scheme}://127.0.0.1:{server.server_port}/", timeout=2.5, slow_ms=800)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
