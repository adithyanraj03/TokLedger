"""Cost models."""

from __future__ import annotations

from tokledger import cost as costmod

PRICES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


def test_local_cost():
    # 1 hour at 300 W = 0.3 kWh
    assert abs(costmod.local_cost_usd(0.3, 0.15) - 0.045) < 1e-12
    assert costmod.local_cost_usd(-1, 0.15) == 0.0


def test_cloud_cost_known_reference():
    # 1M prompt + 100k completion on gpt-4o-mini ref
    v = costmod.cloud_cost_usd("local-model", 1_000_000, 100_000, PRICES, "gpt-4o-mini")
    assert abs(v - (0.15 + 0.06)) < 1e-9


def test_cloud_cost_loose_reference_match():
    v = costmod.cloud_cost_usd("local", 1_000_000, 0, PRICES, "gpt-4o-mini ")
    assert v is not None


def test_cloud_cost_unknown_reference():
    assert costmod.cloud_cost_usd("local", 10, 10, PRICES, "does-not-exist") is None


def test_model_price_loose():
    p = costmod.model_price("GPT-4o-mini", PRICES)
    assert p == PRICES["gpt-4o-mini"]
    assert costmod.model_price("qwen2.5", PRICES) is None


def test_savings_pct():
    assert abs(costmod.savings_pct(0.05, 1.05) - 95.238) < 0.01
    assert costmod.savings_pct(1.0, None) is None
    assert costmod.savings_pct(1.0, 0.0) is None


def test_fmt_usd():
    assert costmod.fmt_usd(None) == "-"
    assert costmod.fmt_usd(0) == "$0.000"
    assert costmod.fmt_usd(0.00012) == "$0.0001"
    assert costmod.fmt_usd(12.3456) == "$12.346"
