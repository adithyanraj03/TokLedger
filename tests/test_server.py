"""The full TokLedger server (API + proxy) against a mock upstream."""

from __future__ import annotations

import json
import socket
import urllib.request

from tokledger import ledger as L
from tokledger.server import run_server


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _post(url, obj):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read()


def test_end_to_end_proxy_to_mock(env):
    """mock upstream -> TokLedger proxy -> ledger row with exact usage."""
    from tokledger.mock import run

    mock_port = _free_port()
    ts_port = _free_port()
    mock_srv = run(mock_port)
    ts_srv = run_server(
        ts_port,
        upstream=f"http://127.0.0.1:{mock_port}/v1",
        proxy=True,
    )
    try:
        status, raw = _post(
            f"http://127.0.0.1:{ts_port}/v1/chat/completions",
            {"model": "mock-7b", "messages": [{"role": "user", "content": "hello world"}]},
        )
        assert status == 200
        obj = json.loads(raw)
        assert obj["choices"][0]["message"]["content"].startswith("tokledger-mock")

        conn = L.connect()
        try:
            rows = L.recent(conn, limit=5)
        finally:
            conn.close()
        assert len(rows) == 1
        r = rows[0]
        assert r["status"] == 200
        assert r["tokens_exact"] == 1
        assert r["prompt_tokens"] > 0 and r["completion_tokens"] > 0
        assert r["kwh"] > 0
        assert r["cloud_cost_usd"] is not None
        assert r["local_cost_usd"] > 0
        assert r["savings_pct"] > 50
    finally:
        ts_srv.shutdown()
        ts_srv.server_close()
        mock_srv.shutdown()
        mock_srv.server_close()


def test_end_to_end_streaming(env):
    from tokledger.mock import run

    mock_port = _free_port()
    ts_port = _free_port()
    mock_srv = run(mock_port)
    ts_srv = run_server(ts_port, upstream=f"http://127.0.0.1:{mock_port}/v1", proxy=True)
    try:
        status, raw = _post(
            f"http://127.0.0.1:{ts_port}/v1/chat/completions",
            {"model": "mock-7b", "stream": True, "messages": [{"role": "user", "content": "hello world"}]},
        )
        assert status == 200
        assert b"data:" in raw and b"[DONE]" in raw

        conn = L.connect()
        try:
            rows = L.recent(conn, limit=5)
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0]["streaming"] == 1
        assert rows[0]["ttft_ms"] is not None
        assert rows[0]["tokens_exact"] == 1
    finally:
        ts_srv.shutdown()
        ts_srv.server_close()
        mock_srv.shutdown()
        mock_srv.server_close()


def test_api_endpoints(env, conn):
    ts_port = _free_port()
    srv = run_server(ts_port, proxy=False)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{ts_port}/health", timeout=10) as resp:
            assert json.loads(resp.read())["ok"] is True

        with urllib.request.urlopen(f"http://127.0.0.1:{ts_port}/api/stats", timeout=10) as resp:
            stats = json.loads(resp.read())
        assert stats["requests"] == 0
        assert stats["upstream"] is None

        with urllib.request.urlopen(f"http://127.0.0.1:{ts_port}/", timeout=10) as resp:
            html = resp.read().decode()
        assert "TokLedger" in html and "local inference ledger" in html

        # seed one row, check by-model / by-day / recent / export
        conn.execute(
            "INSERT INTO requests (ts, model, prompt_tokens, completion_tokens, total_tokens, tokens_exact, local_cost_usd, cloud_cost_usd, status) "
            "VALUES (1700000000, 'm1', 10, 5, 15, 1, 0.001, 0.5, 200)"
        )
        conn.commit()
        with urllib.request.urlopen(f"http://127.0.0.1:{ts_port}/api/by-model", timeout=10) as resp:
            assert json.loads(resp.read())[0]["model"] == "m1"
        with urllib.request.urlopen(f"http://127.0.0.1:{ts_port}/api/recent?limit=5", timeout=10) as resp:
            assert len(json.loads(resp.read())) == 1
        with urllib.request.urlopen(f"http://127.0.0.1:{ts_port}/export.jsonl", timeout=10) as resp:
            line = resp.read().decode().strip()
        assert json.loads(line)["model"] == "m1"
    finally:
        srv.shutdown()
        srv.server_close()


def test_proxy_without_upstream_returns_502(env):
    ts_port = _free_port()
    srv = run_server(ts_port, proxy=True, upstream=None)
    try:
        import urllib.error

        req = urllib.request.Request(
            f"http://127.0.0.1:{ts_port}/v1/chat/completions",
            data=json.dumps({"model": "x", "messages": []}).encode(),
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "expected 502"
        except urllib.error.HTTPError as e:
            assert e.code == 502
            assert "upstream" in json.loads(e.read())["error"]
    finally:
        srv.shutdown()
        srv.server_close()
