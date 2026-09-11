"""JSONL ingest."""

from __future__ import annotations

import json

from tokledger import ingest as I
from tokledger import ledger as L


def test_ingest_tokledger_format(conn, cfg):
    rows = [
        json.dumps(
            {
                "ts": 1700000000.0,
                "model": "m1",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "tokens_exact": 1,
                "total_ms": 900.0,
                "kwh": 0.0005,
                "local_cost_usd": 0.0001,
                "status": 200,
            }
        ),
    ]
    inserted, skipped = I.ingest_iter(rows, conn, cfg)
    assert (inserted, skipped) == (1, 0)
    r = L.recent(conn, limit=1)[0]
    assert r["model"] == "m1"
    # cloud cost filled from the price list because it was absent
    assert r["cloud_cost_usd"] is not None


def test_ingest_minimal_openai_format(conn, cfg):
    rows = [
        json.dumps({"model": "m2", "usage": {"prompt_tokens": 7, "completion_tokens": 3}}),
        "not json at all",
        json.dumps({"model": "m3"}),  # no tokens -> skipped
        "",
    ]
    inserted, skipped = I.ingest_iter(rows, conn, cfg)
    # blank lines are ignored; non-JSON and tokenless lines are skipped
    assert (inserted, skipped) == (1, 2)
    r = L.recent(conn, limit=1)[0]
    assert r["model"] == "m2" and r["prompt_tokens"] == 7 and r["completion_tokens"] == 3


def test_ingest_file_roundtrip(conn, cfg, tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text(
        json.dumps({"model": "m4", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}) + "\n"
    )
    inserted, skipped = I.ingest_file(str(p), conn, cfg)
    assert (inserted, skipped) == (1, 0)
    out = tmp_path / "out.jsonl"
    n = L.export_jsonl(conn, out)
    assert n == 1
