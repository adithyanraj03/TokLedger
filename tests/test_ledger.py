"""SQLite ledger."""

from __future__ import annotations

import time

from tokledger import ledger as L


def _rec(**kw):
    base = {
        "ts": time.time(),
        "model": "qwen2.5-32b",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "tokens_exact": 1,
        "ttft_ms": 120.0,
        "total_ms": 1500.0,
        "tokens_per_s": 33.3,
        "kwh": 0.001,
        "watts": 250.0,
        "power_mode": "static",
        "local_cost_usd": 0.00015,
        "cloud_cost_usd": 0.0375,
        "savings_pct": 99.6,
        "streaming": 1,
        "status": 200,
        "client": "test",
    }
    base.update(kw)
    return base


def test_insert_and_recent(conn):
    i1 = L.insert_record(conn, _rec(model="a", total_tokens=10))
    i2 = L.insert_record(conn, _rec(model="b", total_tokens=20))
    assert i2 > i1
    rows = L.recent(conn, limit=10)
    assert len(rows) == 2
    assert rows[0]["model"] == "b"  # newest first


def test_totals(conn):
    L.insert_record(conn, _rec(prompt_tokens=10, completion_tokens=20, total_tokens=30))
    L.insert_record(conn, _rec(prompt_tokens=30, completion_tokens=40, total_tokens=70, cloud_cost_usd=None))
    t = L.totals(conn)
    assert t["requests"] == 2
    assert t["total_tokens"] == 100
    assert t["priced_requests"] == 1
    assert t["savings_pct"] is not None
    assert t["first_ts"] is not None and t["last_ts"] is not None


def test_by_model(conn):
    L.insert_record(conn, _rec(model="x", total_tokens=5))
    L.insert_record(conn, _rec(model="y", total_tokens=9))
    rows = L.by_model(conn)
    assert [r["model"] for r in rows] == ["y", "x"]  # tokens desc


def test_by_day(conn):
    now = time.time()
    L.insert_record(conn, _rec(ts=now - 86400 * 2, total_tokens=7))
    L.insert_record(conn, _rec(ts=now, total_tokens=3))
    rows = L.by_day(conn)
    assert len(rows) >= 1
    assert sum(r["requests"] for r in rows) == 2


def test_export_roundtrip(conn, tmp_path):
    L.insert_record(conn, _rec())
    out = tmp_path / "x.jsonl"
    n = L.export_jsonl(conn, out)
    assert n == 1
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 1
    import json

    row = json.loads(lines[0])
    assert row["model"] == "qwen2.5-32b"


def test_delete_all(conn):
    L.insert_record(conn, _rec())
    assert L.delete_all(conn) == 1
    assert L.totals(conn)["requests"] == 0
