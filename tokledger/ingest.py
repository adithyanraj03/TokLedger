"""JSONL ingest: import records from TokLedger exports or compatible logs.

Accepted line shapes (one JSON object per line):

1. **TokLedger export** - the full record shape from ``/export.jsonl``
   (all fields; unknown ones ignored).
2. **Minimal OpenAI-style** - at least ``{"model": ..., "usage":
   {"prompt_tokens": ..., "completion_tokens": ...}}``; an optional
   ``"ts"`` (unix epoch) is respected, otherwise the ingest time is used.
   Missing latency/cost fields default to 0 / NULL.

Lines that do not parse or lack a model + token counts are skipped and
reported.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Iterable, List, Tuple

from . import cost as costmod, ledger as ledgermod, tokens as tok


def _normalize(obj: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    model = str(obj.get("model", ""))
    usage = obj.get("usage")
    if isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), (int, float)):
        prompt = int(usage["prompt_tokens"])
        completion = int(usage.get("completion_tokens", 0))
        exact = 1
    else:
        prompt = int(obj.get("prompt_tokens", 0))
        completion = int(obj.get("completion_tokens", 0))
        exact = int(obj.get("tokens_exact", 0))
    if not model or (prompt + completion) <= 0:
        raise ValueError("record needs a model and at least one token")

    total_ms = obj.get("total_ms")
    ts = obj.get("ts")
    kwh = float(obj.get("kwh", 0.0) or 0.0)
    local = float(obj.get("local_cost_usd", 0.0) or 0.0)
    cloud = obj.get("cloud_cost_usd")
    if cloud is None and "cloud_cost_usd" not in obj:
        cloud = costmod.cloud_cost_usd(
            model, prompt, completion,
            cfg.get("cloud_prices", {}), cfg.get("cloud_reference_model", "gpt-4o-mini"),
        )
    return {
        "ts": float(ts) if ts else None,
        "model": model,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": int(obj.get("total_tokens", prompt + completion)),
        "tokens_exact": exact,
        "ttft_ms": obj.get("ttft_ms"),
        "total_ms": float(total_ms) if total_ms else None,
        "tokens_per_s": obj.get("tokens_per_s"),
        "kwh": kwh,
        "watts": obj.get("watts"),
        "power_mode": obj.get("power_mode"),
        "local_cost_usd": local,
        "cloud_cost_usd": cloud,
        "savings_pct": costmod.savings_pct(local, cloud),
        "streaming": int(obj.get("streaming", 0)),
        "status": int(obj.get("status", 200)),
        "error": obj.get("error"),
        "client": obj.get("client", "ingest"),
        "preview": obj.get("preview"),
    }


def ingest_iter(
    lines: Iterable[str], conn: sqlite3.Connection, cfg: Dict[str, Any]
) -> Tuple[int, int]:
    """Ingest JSON lines; returns (inserted, skipped)."""
    inserted = skipped = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            rec = _normalize(obj, cfg)
        except (json.JSONDecodeError, ValueError, TypeError):
            skipped += 1
            continue
        if rec["ts"] is None:
            import time

            rec["ts"] = time.time()
        ledgermod.insert_record(conn, rec)
        inserted += 1
    return inserted, skipped


def ingest_file(path: str, conn: sqlite3.Connection, cfg: Dict[str, Any]) -> Tuple[int, int]:
    with open(path, "r", encoding="utf-8") as f:
        return ingest_iter(f, conn, cfg)
