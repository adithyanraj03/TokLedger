"""Shared fixtures: isolated TOKLEDGER_DATA + a seeded connection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKLEDGER_DATA", str(tmp_path / "data"))
    from tokledger import config

    monkeypatch.setattr(config, "DEFAULT_CONFIG", dict(config.DEFAULT_CONFIG))
    return tmp_path


@pytest.fixture()
def conn(env):
    from tokledger import ledger

    c = ledger.connect()
    yield c
    c.close()


@pytest.fixture()
def cfg(env):
    from tokledger.config import load_config

    return load_config()
