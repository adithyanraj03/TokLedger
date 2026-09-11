"""The TokLedger HTTP server: proxy + API + dashboard.

Pure standard library (``http.server`` + ``urllib``). Endpoints:

Proxy (requires an upstream in config.json or ``--upstream``):

* ``POST /v1/chat/completions`` - OpenAI-compatible, streaming + not

API (always available):

* ``GET /health``          - liveness
* ``GET /api/stats``       - aggregate totals
* ``GET /api/recent``      - latest N records (?limit=)
* ``GET /api/by-model``    - per-model rollup
* ``GET /api/by-day``      - per-day rollup
* ``GET /export.jsonl``    - full ledger export

Dashboard:

* ``GET /`` - the zero-dependency single-page dashboard
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import __version__, dashboard, ledger as ledgermod
from .config import load_config
from .power import PowerSampler
from .proxy import (
    ProxyUpstreamError,
    process_non_streaming,
    process_streaming,
)

# --------------------------------------------------------------------------
# upstream transport
# --------------------------------------------------------------------------


def _upstream_call(upstream: str):
    """Return caller(body, streaming) -> (status, bytes | iterator[bytes]).

    For streaming, the upstream response is kept open until the iterator is
    exhausted (its ``finally`` closes it), so the proxy can measure and
    forward the whole stream.
    """

    def call(body: bytes, streaming: bool) -> Tuple[int, Any]:
        req = urllib.request.Request(
            upstream.rstrip("/") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as e:
            detail = e.read()[:500].decode("utf-8", "replace")
            raise ProxyUpstreamError(e.code, detail or str(e)) from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ProxyUpstreamError(502, f"upstream unreachable: {e}") from e

        if not streaming:
            try:
                return resp.status, resp.read()
            finally:
                resp.close()

        def chunks() -> Iterator[bytes]:
            try:
                while True:
                    part = resp.read(4096)
                    if not part:
                        break
                    yield part
            finally:
                resp.close()

        return resp.status, chunks()

    return call


# --------------------------------------------------------------------------
# handler
# --------------------------------------------------------------------------


class TokLedgerHandler(BaseHTTPRequestHandler):
    server_version = f"TokLedger/{__version__}"
    # set by run_server
    app: Dict[str, Any] = {}

    def log_message(self, *args):  # quiet by default
        pass

    # -- helpers -----------------------------------------------------------

    def _json(self, status: int, obj: Any):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, status: int, text: str):
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _conn(self):
        return self.app["connect"]()

    # -- API ---------------------------------------------------------------

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        path = url.path
        qs = parse_qs(url.query)

        if path == "/":
            self._html(200, dashboard.DASHBOARD_HTML)
        elif path == "/health":
            self._json(200, {"ok": True, "version": __version__})
        elif path == "/api/stats":
            with self._conn() as conn:
                stats = ledgermod.totals(conn)
            stats["version"] = __version__
            stats["power_mode"] = self.app["sampler"].mode
            stats["upstream"] = self.app["upstream"]
            self._json(200, stats)
        elif path == "/api/recent":
            limit = int(qs.get("limit", ["50"])[0])
            with self._conn() as conn:
                rows = ledgermod.recent(conn, limit=limit)
            self._json(200, rows)
        elif path == "/api/by-model":
            with self._conn() as conn:
                rows = ledgermod.by_model(conn)
            self._json(200, rows)
        elif path == "/api/by-day":
            with self._conn() as conn:
                rows = ledgermod.by_day(conn)
            self._json(200, rows)
        elif path == "/export.jsonl":
            with self._conn() as conn:
                text = ledgermod.export_text(conn)
            payload = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Disposition", 'attachment; filename="tokledger-export.jsonl"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self._json(404, {"error": "not found"})

    # -- proxy -------------------------------------------------------------

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": "not found"})
            return

        upstream = self.app["upstream"]
        if not upstream:
            self._json(
                502,
                {
                    "error": "no upstream configured",
                    "hint": "set config.json 'upstream' (e.g. http://127.0.0.1:8080/v1) or run: tokledger proxy --upstream URL",
                },
            )
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            self._json(400, {"error": "request body is not valid JSON"})
            return

        cfg = self.app["config"]
        sampler = self.app["sampler"]
        caller = _upstream_call(upstream)
        streaming = bool(request.get("stream"))

        if streaming:
            outcome = process_streaming(request, caller, cfg, sampler)
            with self._conn() as conn:
                ledgermod.insert_record(conn, outcome.record)
            self.send_response(outcome.status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in outcome.chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        else:
            outcome = process_non_streaming(request, caller, cfg, sampler)
            with self._conn() as conn:
                ledgermod.insert_record(conn, outcome.record)
            self._json(outcome.status, json.loads(outcome.response_body or b"{}"))


# --------------------------------------------------------------------------
# server factory
# --------------------------------------------------------------------------


def build_server(
    port: int,
    host: str = "127.0.0.1",
    upstream: Optional[str] = None,
    proxy: bool = True,
) -> ThreadingHTTPServer:
    cfg = load_config()
    effective_upstream = upstream or cfg.get("upstream")
    sampler = PowerSampler(
        load_watts=cfg.get("load_watts", 300.0), idle_watts=cfg.get("idle_watts", 20.0)
    )
    handler = type("BoundHandler", (TokLedgerHandler,), {})
    handler.app = {
        "config": cfg,
        "sampler": sampler,
        "upstream": effective_upstream if proxy else None,
        "connect": ledgermod.connect,
    }
    srv = ThreadingHTTPServer((host, port), handler)
    return srv


def run_server(
    port: int,
    host: str = "127.0.0.1",
    upstream: Optional[str] = None,
    proxy: bool = True,
) -> ThreadingHTTPServer:
    """Start the server in a daemon thread; returns the server object."""
    srv = build_server(port, host, upstream=upstream, proxy=proxy)
    t = threading.Thread(target=srv.serve_forever, name="tokledger-http", daemon=True)
    t.start()
    return srv
