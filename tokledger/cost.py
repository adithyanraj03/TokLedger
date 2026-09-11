"""Cost models: local (energy) and cloud-equivalent.

* **Local cost** = kWh x ``usd_per_kwh``.
* **Cloud-equivalent cost** = the price the reference cloud API would have
  charged for the same token counts, from the editable price list in
  ``config.json`` (USD per 1M tokens). Local models are free at the token
  level, so this column is the number people argue about on r/LocalLLaMA.

``cloud_cost`` returns ``None`` for models with no price-list entry rather
than 0, so the UI can distinguish "unknown price" from "cost is zero".
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def local_cost_usd(kwh: float, usd_per_kwh: float) -> float:
    return max(0.0, kwh) * max(0.0, usd_per_kwh)


def _normalize(name: str) -> str:
    return (
        name.lower()
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
        .replace(" ", "")
        .replace(".", "")
    )


def cloud_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    price_list: Dict[str, Dict[str, float]],
    reference_model: str,
) -> Optional[float]:
    """USD the reference cloud model would cost for these token counts.

    The price list is keyed by reference-model names; the *local* model name
    does not need to match (a local "qwen2.5-32b" is still compared against
    the configured cloud reference). The local model name is only used to
    look up a price when the caller explicitly prices cloud models through
    the proxy.

    Returns None when the reference model has no price entry.
    """
    ref = price_list.get(reference_model)
    if ref is None:
        # try to find the reference by a loose name match
        want = _normalize(reference_model)
        for key, val in price_list.items():
            if _normalize(key) == want:
                ref = val
                break
    if ref is None:
        return None
    return (
        (prompt_tokens / 1e6) * float(ref.get("input", 0.0))
        + (completion_tokens / 1e6) * float(ref.get("output", 0.0))
    )


def model_price(
    model: str, price_list: Dict[str, Dict[str, float]]
) -> Optional[Dict[str, float]]:
    """Price entry for a (possibly cloud) model name, loose match."""
    if model in price_list:
        return price_list[model]
    want = _normalize(model)
    for key, val in price_list.items():
        if _normalize(key) == want or want in _normalize(key) or _normalize(key) in want:
            return val
    return None


def savings_pct(local_cost: float, cloud_cost: Optional[float]) -> Optional[float]:
    """Percent saved vs the cloud equivalent (None when unknown)."""
    if cloud_cost is None or cloud_cost <= 0:
        return None
    return (1.0 - local_cost / cloud_cost) * 100.0


def fmt_usd(v: Optional[float]) -> str:
    if v is None:
        return "-"
    if v == 0:
        return "$0.000"
    if v < 0.001:
        return f"${v:.4f}"
    return f"${v:.3f}"
