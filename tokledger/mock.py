"""A deterministic mock OpenAI-compatible provider.

``tokledger mock --port 8999`` runs a tiny stdlib HTTP server that speaks
just enough of the OpenAI chat completions API (streaming + non-streaming,
``/v1/models``) to exercise the whole TokLedger pipeline offline - no model,
no GPU, no network beyond localhost.

Responses are deterministic: the completion text is a fixed template that
embeds the prompt length, so repeated runs produce identical token counts.
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

MAGIC = "tokledger-mock"
MODELS = ["mock-7b", "mock-32b"]
# small deterministic delays so the demo's latency/tok-s numbers look like a
# real engine (streaming ~5 ms per chunk, non-streaming ~30 ms)
CHUNK_DELAY_S = 0.005
REPLY_DELAY_S = 0.03


def completion_text(prompt_chars: int) -> str:
    return (
        f"{MAGIC} response for a {prompt_chars}-character prompt. "
        "The local ledger records every token, millisecond, and watt of "
        "this exchange. Deterministic, offline, and free - exactly the "
        "point of running your own inference."
    )


def prompt_chars_from(body: Dict[str, Any]) -> int:
    total = 0
    msgs = body.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                total += len(m["content"])
    return total


def _chunk(index: int, text: str, done: bool) -> str:
    obj: Dict[str, Any] = {
        "id": f"mock-{index}",
        "object": "chat.completion.chunk",
        "model": MODELS[0],
        "choices": [
            {
                "index": 0,
                "delta": ({} if done else {"content": text}),
                "finish_reason": "stop" if done else None,
            }
        ],
    }
    if done:
        obj["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return f"data: {json.dumps(obj)}\n\n"


def build_non_streaming(body: Dict[str, Any]) -> Dict[str, Any]:
    n = prompt_chars_from(body)
    text = completion_text(n)
    return {
        "id": "mock-1",
        "object": "chat.completion",
        "model": body.get("model", MODELS[0]),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        # exact usage, like llama.cpp with include_usage
        "usage": {"prompt_tokens": max(1, n // 4), "completion_tokens": max(1, len(text) // 4), "total_tokens": 0},
    }


def build_sse(body: Dict[str, Any]) -> List[bytes]:
    n = prompt_chars_from(body)
    text = completion_text(n)
    parts = [text[i : i + 24] for i in range(0, len(text), 24)]
    chunks: List[bytes] = []
    for i, p in enumerate(parts):
        chunks.append(_chunk(i, p, done=False).encode("utf-8"))
    # final chunk carries usage (like llama.cpp stream_options.include_usage)
    final = {
        "id": "mock-final",
        "object": "chat.completion.chunk",
        "model": body.get("model", MODELS[0]),
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": max(1, n // 4),
            "completion_tokens": max(1, len(text) // 4),
            "total_tokens": 0,
        },
    }
    chunks.append(f"data: {json.dumps(final)}\n\n".encode("utf-8"))
    chunks.append(b"data: [DONE]\n\n")
    return chunks


class MockHandler(BaseHTTPRequestHandler):
    server_version = "TokLedgerMock/0.1"

    def log_message(self, *args):  # silence
        pass

    def _send(self, status: int, payload: bytes, ctype: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/v1/models", "/models"):
            self._send(200, json.dumps({"data": [{"id": m} for m in MODELS]}).encode())
        elif path == "/health":
            self._send(200, b'{"ok": true}')
        else:
            self._send(404, b'{"error": "not found"}')

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send(404, b'{"error": "not found"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            self._send(400, b'{"error": "bad json"}')
            return
        if body.get("stream"):
            chunks = build_sse(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for c in chunks:
                self.wfile.write(c)
                self.wfile.flush()
                time.sleep(CHUNK_DELAY_S)
        else:
            time.sleep(REPLY_DELAY_S)
            self._send(200, json.dumps(build_non_streaming(body)).encode())


def run(port: int = 8999, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Start the mock provider on a daemon thread; returns the server."""
    import threading

    srv = ThreadingHTTPServer((host, port), MockHandler)
    t = threading.Thread(target=srv.serve_forever, name="tokledger-mock", daemon=True)
    t.start()
    return srv
