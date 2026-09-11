"""Seed a realistic synthetic 3-day workload into the ledger.

Produces deterministic demo data (fixed seed) so screenshots and the
sample report are reproducible:

    python examples/seed_demo.py            # seed the default ledger
    TOKLEDGER_DATA=/tmp/tl python examples/seed_demo.py

Mixes models, prompt sizes, streaming and non-streaming requests, a few
errors, and a slow day - everything the dashboard is built to show.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tokledger import ledger as L  # noqa: E402
from tokledger.config import load_config  # noqa: E402
from tokledger import cost as C  # noqa: E402

MODELS = [
    ("qwen2.5-32b", 0.40),      # (model, share of traffic)
    ("llama3.1-8b-instruct", 0.30),
    ("mistral-nemo-12b", 0.20),
    ("phi-4-14b", 0.10),
]

PROMPTS = [
    "Summarize this log file and point out the anomalies.",
    "Refactor this function for readability; keep the API identical.",
    "Explain backpropagation with a concrete example and a diagram description.",
    "Write a pytest suite for the attached module.",
    "Translate this paragraph into formal technical German.",
    "Review this PR diff and list the risks in order of severity.",
    "Draft a release note for these changes, max three bullets.",
    "Plan the migration from monolith to services; assume 4 engineers.",
]


def seed(days: int = 3, seed_int: int = 20260911) -> int:
    rng = random.Random(seed_int)
    cfg = load_config()
    conn = L.connect()
    inserted = 0
    now = datetime.now(timezone.utc)
    for d in range(days - 1, -1, -1):
        day = now - timedelta(days=d)
        n_requests = rng.choice([140, 180, 230, 290]) if d else 90
        for _ in range(n_requests):
            hour = day.replace(hour=rng.randint(8, 23), minute=rng.randint(0, 59), second=rng.randint(0, 59))
            ts = hour.timestamp()
            model = rng.choices([m for m, _ in MODELS], weights=[w for _, w in MODELS])[0]
            prompt = rng.choice(PROMPTS) + " " + "context " * rng.randint(5, 120)
            streaming = rng.random() < 0.6
            prompt_tokens = max(1, len(prompt) // 4)
            completion_tokens = max(1, int(rng.gauss(220, 90)))
            total = prompt_tokens + completion_tokens
            ttft = max(20.0, rng.gauss(140.0, 60.0))
            tps = max(4.0, rng.gauss(42.0, 12.0))
            total_ms = ttft + (completion_tokens / tps) * 1000.0
            watts = 180.0 + 140.0 * min(1.0, completion_tokens / 600.0) + rng.gauss(0, 8.0)
            kwh = watts * (total_ms / 1000.0) / 3_600_000.0
            local_usd = C.local_cost_usd(kwh, cfg.get("usd_per_kwh", 0.15))
            cloud_usd = C.cloud_cost_usd(model, prompt_tokens, completion_tokens,
                                         cfg.get("cloud_prices", {}),
                                         cfg.get("cloud_reference_model", "gpt-4o-mini"))
            ok = rng.random() > 0.02
            conn.execute(
                """INSERT INTO requests
                   (ts, model, prompt_tokens, completion_tokens, total_tokens, tokens_exact,
                    ttft_ms, total_ms, tokens_per_s, kwh, watts, power_mode,
                    local_cost_usd, cloud_cost_usd, savings_pct, streaming, status, error, client, preview)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts, model, prompt_tokens, completion_tokens, total, 1,
                    round(ttft, 1), round(total_ms, 1), round(tps, 2), kwh,
                    round(watts, 1), "static", local_usd, cloud_usd,
                    C.savings_pct(local_usd, cloud_usd), int(streaming),
                    200 if ok else rng.choice([413, 500, 503]),
                    None if ok else "synthetic failure for demo",
                    rng.choice(["swarm-planner", "swarm-worker", "notebook"]),
                    prompt[:160],
                ),
            )
            inserted += 1
    conn.commit()
    conn.close()
    return inserted


if __name__ == "__main__":
    n = seed()
    print(f"seeded {n} synthetic requests into {L.db_path()}")
