"""Paths and configuration for TokLedger.

All state lives in one directory (default ``~/.tokledger``; override with
``$TOKLEDGER_DATA`` for tests / CI):

* ``ledger.db``   - SQLite ledger
* ``config.json`` - power model, electricity rate, cloud reference prices,
                    optional upstream URL

The config is user-editable JSON; unknown keys are preserved on save.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

_DATA_ENV = "TOKLEDGER_DATA"

#: Reference cloud price list, USD per 1M tokens.
#: Kept intentionally small and conservative; edit config.json to change.
DEFAULT_CLOUD_PRICES = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "upstream": None,  # e.g. "http://127.0.0.1:8080/v1" (llama.cpp) or ...:11434/v1 (Ollama)
    # Power model: when pynvml + an NVIDIA GPU are available the live draw is
    # sampled; otherwise these configured values are used.
    "idle_watts": 20.0,
    "load_watts": 300.0,
    "usd_per_kwh": 0.15,
    # Which reference cloud price to use for the "cloud-equivalent" column.
    "cloud_reference_model": "gpt-4o-mini",
    "cloud_prices": DEFAULT_CLOUD_PRICES,
    # Optional: tag every record with a client name (e.g. "swarm-planner").
    "client": "tokledger",
}


def data_dir() -> Path:
    root = Path(os.environ.get(_DATA_ENV, str(Path.home() / ".tokledger")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def db_path() -> Path:
    return data_dir() / "ledger.db"


def config_path() -> Path:
    return data_dir() / "config.json"


def default_config() -> Dict[str, Any]:
    # deep copy so callers cannot mutate the module default
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config() -> Dict[str, Any]:
    """Load config, merging over defaults (unknown keys preserved)."""
    cfg = default_config()
    p = config_path()
    if p.exists():
        try:
            user = json.loads(p.read_text())
            for k, v in user.items():
                cfg[k] = v
            # merge price list rather than replacing it
            if isinstance(cfg.get("cloud_prices"), dict) and isinstance(
                DEFAULT_CLOUD_PRICES, dict
            ):
                merged = dict(DEFAULT_CLOUD_PRICES)
                merged.update(cfg["cloud_prices"])
                cfg["cloud_prices"] = merged
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    config_path().write_text(json.dumps(cfg, indent=2) + "\n")


def update_config(**kwargs) -> Dict[str, Any]:
    cfg = load_config()
    cfg.update(kwargs)
    save_config(cfg)
    return cfg
