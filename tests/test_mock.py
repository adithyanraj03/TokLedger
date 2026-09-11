"""Mock provider over a real (localhost) HTTP connection."""

from __future__ import annotations

import json
import socket
import urllib.request


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_mock_non_streaming(env):
    from tokledger.mock import run

    port = _free_port()
    srv = run(port)
    try:
        body = json.dumps({"model": "mock-7b", "messages": [{"role": "user", "content": "hi there"}]}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            obj = json.loads(resp.read())
        assert obj["choices"][0]["message"]["role"] == "assistant"
        assert obj["usage"]["prompt_tokens"] > 0
        assert obj["usage"]["completion_tokens"] > 0
    finally:
        srv.shutdown()
        srv.server_close()


def test_mock_streaming_sse(env):
    from tokledger.mock import run

    port = _free_port()
    srv = run(port)
    try:
        body = json.dumps({"model": "mock-7b", "stream": True,
                           "messages": [{"role": "user", "content": "hi there"}]}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode()
        lines = [l for l in raw.splitlines() if l.startswith("data:")]
        assert lines[-1] == "data: [DONE]"
        payloads = [json.loads(l[5:].strip()) for l in lines[:-1]]
        # the final chunk carries usage
        assert "usage" in payloads[-1]
        text = "".join(p["choices"][0]["delta"].get("content", "") for p in payloads)
        assert "tokledger-mock" in text
    finally:
        srv.shutdown()
        srv.server_close()


def test_mock_models_and_health(env):
    from tokledger.mock import run

    port = _free_port()
    srv = run(port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as resp:
            obj = json.loads(resp.read())
        assert any(m["id"] == "mock-7b" for m in obj["data"])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as resp:
            assert json.loads(resp.read())["ok"] is True
    finally:
        srv.shutdown()
        srv.server_close()
