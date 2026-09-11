"""SQLite ledger: one row per LLM request.

Schema (``requests``):

* id, ts (unix epoch float, UTC), model
* prompt_tokens, completion_tokens, total_tokens, tokens_exact (0/1)
* ttft_ms, total_ms, tokens_per_s
* kwh, watts, power_mode
* local_cost_usd, cloud_cost_usd (NULL = unknown price), savings_pct
* streaming (0/1), status (200/5xx/...), error, client, preview
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    tokens_exact INTEGER NOT NULL DEFAULT 0,
    ttft_ms REAL,
    total_ms REAL,
    tokens_per_s REAL,
    kwh REAL NOT NULL DEFAULT 0,
    watts REAL,
    power_mode TEXT,
    local_cost_usd REAL NOT NULL DEFAULT 0,
    cloud_cost_usd REAL,
    savings_pct REAL,
    streaming INTEGER NOT NULL DEFAULT 0,
    status INTEGER NOT NULL DEFAULT 200,
    error TEXT,
    client TEXT,
    preview TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(model);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def insert_record(conn: sqlite3.Connection, rec: Dict[str, Any]) -> int:
    conn.execute(
        """INSERT INTO requests (
            ts, model, prompt_tokens, completion_tokens, total_tokens,
            tokens_exact, ttft_ms, total_ms, tokens_per_s, kwh, watts,
            power_mode, local_cost_usd, cloud_cost_usd, savings_pct,
            streaming, status, error, client, preview
        ) VALUES (
            :ts, :model, :prompt_tokens, :completion_tokens, :total_tokens,
            :tokens_exact, :ttft_ms, :total_ms, :tokens_per_s, :kwh, :watts,
            :power_mode, :local_cost_usd, :cloud_cost_usd, :savings_pct,
            :streaming, :status, :error, :client, :preview
        )""",
        {
            "ts": rec.get("ts", now_ts()),
            "model": str(rec.get("model", "unknown")),
            "prompt_tokens": int(rec.get("prompt_tokens", 0)),
            "completion_tokens": int(rec.get("completion_tokens", 0)),
            "total_tokens": int(rec.get("total_tokens", 0)),
            "tokens_exact": int(rec.get("tokens_exact", 0)),
            "ttft_ms": rec.get("ttft_ms"),
            "total_ms": rec.get("total_ms"),
            "tokens_per_s": rec.get("tokens_per_s"),
            "kwh": float(rec.get("kwh", 0.0)),
            "watts": rec.get("watts"),
            "power_mode": rec.get("power_mode"),
            "local_cost_usd": float(rec.get("local_cost_usd", 0.0)),
            "cloud_cost_usd": rec.get("cloud_cost_usd"),
            "savings_pct": rec.get("savings_pct"),
            "streaming": int(rec.get("streaming", 0)),
            "status": int(rec.get("status", 200)),
            "error": rec.get("error"),
            "client": rec.get("client"),
            "preview": rec.get("preview"),
        },
    )
    conn.commit()
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def totals(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute(
        """SELECT
            COUNT(*) AS requests,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            AVG(ttft_ms) AS avg_ttft_ms,
            AVG(total_ms) AS avg_total_ms,
            COALESCE(SUM(kwh), 0) AS kwh,
            COALESCE(SUM(local_cost_usd), 0) AS local_cost_usd,
            COALESCE(SUM(CASE WHEN cloud_cost_usd IS NOT NULL THEN cloud_cost_usd END), 0)
                AS cloud_cost_usd,
            COUNT(CASE WHEN cloud_cost_usd IS NOT NULL THEN 1 END) AS priced_requests,
            MAX(ts) AS last_ts
        FROM requests"""
    ).fetchone()
    d = dict(row)
    if d["cloud_cost_usd"] and d["priced_requests"]:
        d["savings_pct"] = (1.0 - d["local_cost_usd"] / d["cloud_cost_usd"]) * 100.0
    else:
        d["savings_pct"] = None
    d["first_ts"] = conn.execute("SELECT MIN(ts) FROM requests").fetchone()[0]
    return d


def by_model(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """SELECT model,
                  COUNT(*) AS requests,
                  SUM(total_tokens) AS total_tokens,
                  AVG(ttft_ms) AS avg_ttft_ms,
                  SUM(local_cost_usd) AS local_cost_usd,
                  SUM(CASE WHEN cloud_cost_usd IS NOT NULL THEN cloud_cost_usd END)
                      AS cloud_cost_usd
           FROM requests GROUP BY model ORDER BY total_tokens DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def by_day(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """SELECT date(ts, 'unixepoch') AS day,
                  COUNT(*) AS requests,
                  SUM(total_tokens) AS total_tokens,
                  SUM(local_cost_usd) AS local_cost_usd,
                  SUM(CASE WHEN cloud_cost_usd IS NOT NULL THEN cloud_cost_usd END)
                      AS cloud_cost_usd
           FROM requests GROUP BY day ORDER BY day"""
    ).fetchall()
    return [dict(r) for r in rows]


def recent(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM requests ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    return [dict(r) for r in rows]


def export_text(conn: sqlite3.Connection) -> str:
    """Full ledger as JSONL text (no file I/O - the HTTP server uses this)."""
    rows = conn.execute("SELECT * FROM requests ORDER BY id").fetchall()
    return "".join(json.dumps(dict(r), default=str) + "\n" for r in rows)


def export_jsonl(conn: sqlite3.Connection, path: Path) -> int:
    text = export_text(conn)
    Path(path).write_text(text, encoding="utf-8")
    return len(text.splitlines()) if text.strip() else 0


def delete_all(conn: sqlite3.Connection) -> int:
    n = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    conn.execute("DELETE FROM requests")
    conn.commit()
    return int(n)
