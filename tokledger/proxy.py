"""Proxy logic for OpenAI-compatible chat completions.

The transport (urllib) lives in :mod:`tokledger.server`; this module is the
pure, unit-testable core: given a request body and an *injectable* upstream
caller, it measures TTFT / latency, extracts tokens (exact usage when the
engine reports it, heuristic otherwise), computes energy + costs, and
returns a ledger-ready record.

Upstream caller protocol
------------------------
``caller(body: bytes, streaming: bool)`` returns ``(status, body_iterator)``
where ``body_iterator`` yields bytes of the upstream response body (the
complete JSON for non-streaming, or raw SSE bytes for streaming). Raising
``ProxyUpstreamError`` records the failure.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from . import cost as costmod
from . import tokens as tok
from .config import load_config
from .power import PowerSampler


class ProxyUpstreamError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class ProxyOutcome:
    status: int
    response_body: bytes  # non-streaming: full JSON; streaming: b"" (already forwarded)
    record: Dict[str, Any]
    chunks: List[bytes] = field(default_factory=list)  # streaming: SSE bytes to forward


def _parse_sse_lines(data: Iterable[bytes]) -> Iterator[bytes]:
    """Yield the JSON payload of each ``data:`` SSE line (buffered)."""
    buf = b""
    for chunk in data:
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                continue
            try:
                json.loads(payload.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            yield payload


def _record_base(cfg: Dict[str, Any], request: Dict[str, Any], sampler: PowerSampler) -> Dict[str, Any]:
    model = str(request.get("model", "unknown"))
    preview = tok.first_message_preview(request.get("messages"))
    return {
        "model": model,
        "client": cfg.get("client", "tokledger"),
        "preview": preview or None,
    }


def process_non_streaming(
    request: Dict[str, Any],
    caller: Callable[[bytes, bool], Tuple[int, bytes]],
    cfg: Dict[str, Any],
    sampler: PowerSampler,
) -> ProxyOutcome:
    """Handle a non-streaming chat completion."""
    body = json.dumps(request).encode("utf-8")
    t_wall = time.time()
    t0 = time.perf_counter()
    w_before = sampler.sample_watts()
    try:
        status, payload = caller(body, streaming=False)
    except ProxyUpstreamError as e:
        record = _record_base(cfg, request, sampler)
        record.update(
            {
                "ts": t_wall,
                "status": e.status,
                "error": e.detail[:500],
                "total_ms": (time.perf_counter() - t0) * 1000.0,
                "kwh": 0.0,
                "watts": None,
                "power_mode": None,
                "local_cost_usd": 0.0,
                "cloud_cost_usd": None,
                "prompt_tokens": tok.count_prompt_tokens(request.get("messages")),
                "completion_tokens": 0,
                "total_tokens": tok.count_prompt_tokens(request.get("messages")),
                "tokens_exact": 0,
                "streaming": 0,
            }
        )
        return ProxyOutcome(status=e.status, response_body=e.detail.encode("utf-8"), record=record)

    elapsed_s = time.perf_counter() - t0
    w_after = sampler.sample_watts()
    watts = (w_before + w_after) / 2.0
    kwh = sampler.kwh_for(elapsed_s, watts)
    local_usd = costmod.local_cost_usd(kwh, cfg.get("usd_per_kwh", 0.15))

    try:
        resp = json.loads(payload.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        resp = {}
    usage = tok.parse_usage(resp)
    prompt_est = tok.count_prompt_tokens(request.get("messages"))
    if usage is not None:
        prompt_tokens, completion_tokens = usage
        exact = 1
    else:
        prompt_tokens = prompt_est
        completion_text = ""
        try:
            completion_text = resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            pass
        completion_tokens = tok.count_tokens(completion_text)
        exact = 0

    total = prompt_tokens + completion_tokens
    total_ms = elapsed_s * 1000.0
    cloud_usd = costmod.cloud_cost_usd(
        str(request.get("model", "")),
        prompt_tokens,
        completion_tokens,
        cfg.get("cloud_prices", {}),
        cfg.get("cloud_reference_model", "gpt-4o-mini"),
    )
    record = _record_base(cfg, request, sampler)
    record.update(
        {
            "ts": t_wall,
            "status": status,
            "error": None if status == 200 else "upstream error",
            "ttft_ms": total_ms,  # non-streaming: first byte == whole response
            "total_ms": total_ms,
            "tokens_per_s": (completion_tokens / elapsed_s) if elapsed_s > 0 else None,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total,
            "tokens_exact": exact,
            "kwh": kwh,
            "watts": watts,
            "power_mode": sampler.mode,
            "local_cost_usd": local_usd,
            "cloud_cost_usd": cloud_usd,
            "savings_pct": costmod.savings_pct(local_usd, cloud_usd),
            "streaming": 0,
        }
    )
    return ProxyOutcome(status=status, response_body=payload, record=record)


def process_streaming(
    request: Dict[str, Any],
    caller: Callable[[bytes, bool], Tuple[int, Iterator[bytes]]],
    cfg: Dict[str, Any],
    sampler: PowerSampler,
) -> ProxyOutcome:
    """Handle a streaming chat completion.

    Every upstream SSE byte is collected so the caller can forward it
    verbatim to the client; token usage is parsed from the final chunk when
    the engine reports it, else estimated from the delta text.
    """
    body = json.dumps(request).encode("utf-8")
    t_wall = time.time()
    t0 = time.perf_counter()
    w_before = sampler.sample_watts()
    try:
        status, stream = caller(body, streaming=True)
    except ProxyUpstreamError as e:
        record = _record_base(cfg, request, sampler)
        record.update(
            {
                "ts": t_wall,
                "status": e.status,
                "error": e.detail[:500],
                "total_ms": (time.perf_counter() - t0) * 1000.0,
                "prompt_tokens": tok.count_prompt_tokens(request.get("messages")),
                "completion_tokens": 0,
                "total_tokens": tok.count_prompt_tokens(request.get("messages")),
                "tokens_exact": 0,
                "kwh": 0.0,
                "watts": None,
                "power_mode": None,
                "local_cost_usd": 0.0,
                "cloud_cost_usd": None,
                "streaming": 1,
            }
        )
        return ProxyOutcome(status=e.status, response_body=e.detail.encode("utf-8"), record=record)

    raw_chunks: List[bytes] = []
    payloads: List[Any] = []
    deltas: List[str] = []
    ttft_ms: Optional[float] = None
    for chunk in stream:
        if ttft_ms is None and chunk:
            ttft_ms = (time.perf_counter() - t0) * 1000.0
        raw_chunks.append(chunk)
        for payload in _parse_sse_lines([chunk]):
            try:
                obj = json.loads(payload.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            payloads.append(obj)
            try:
                delta = obj["choices"][0].get("delta", {})
                content = delta.get("content")
                if isinstance(content, str) and content:
                    deltas.append(content)
            except (KeyError, IndexError, TypeError):
                continue

    elapsed_s = time.perf_counter() - t0
    w_after = sampler.sample_watts()
    watts = (w_before + w_after) / 2.0
    kwh = sampler.kwh_for(elapsed_s, watts)
    local_usd = costmod.local_cost_usd(kwh, cfg.get("usd_per_kwh", 0.15))

    usage = tok.usage_from_sse_chunks(payloads)
    prompt_est = tok.count_prompt_tokens(request.get("messages"))
    if usage is not None:
        prompt_tokens, completion_tokens = usage
        exact = 1
    else:
        prompt_tokens = prompt_est
        completion_tokens = tok.completion_tokens_from_deltas(deltas)
        exact = 0

    total = prompt_tokens + completion_tokens
    total_ms = elapsed_s * 1000.0
    cloud_usd = costmod.cloud_cost_usd(
        str(request.get("model", "")),
        prompt_tokens,
        completion_tokens,
        cfg.get("cloud_prices", {}),
        cfg.get("cloud_reference_model", "gpt-4o-mini"),
    )
    record = _record_base(cfg, request, sampler)
    record.update(
        {
            "ts": t_wall,
            "status": status,
            "error": None if status == 200 else "upstream error",
            "ttft_ms": ttft_ms,
            "total_ms": total_ms,
            "tokens_per_s": (completion_tokens / elapsed_s) if elapsed_s > 0 else None,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total,
            "tokens_exact": exact,
            "kwh": kwh,
            "watts": watts,
            "power_mode": sampler.mode,
            "local_cost_usd": local_usd,
            "cloud_cost_usd": cloud_usd,
            "savings_pct": costmod.savings_pct(local_usd, cloud_usd),
            "streaming": 1,
        }
    )
    return ProxyOutcome(status=status, response_body=b"", record=record, chunks=raw_chunks)
