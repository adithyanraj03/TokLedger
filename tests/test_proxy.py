"""Proxy core with an injected fake upstream."""

from __future__ import annotations

import json

from tokledger import proxy as P
from tokledger.power import PowerSampler


def _cfg():
    return {
        "client": "test",
        "usd_per_kwh": 0.15,
        "cloud_prices": {"gpt-4o-mini": {"input": 0.15, "output": 0.60}},
        "cloud_reference_model": "gpt-4o-mini",
        "load_watts": 300.0,
        "idle_watts": 20.0,
    }


def _request(stream=False):
    return {
        "model": "qwen2.5-32b",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Explain a roofline. " * 10},
        ],
        "stream": stream,
    }


def _sampler():
    return PowerSampler(load_watts=300.0, idle_watts=20.0)


# ---------------------------------------------------------------------------


def test_non_streaming_with_usage():
    resp = {
        "id": "1",
        "model": "qwen2.5-32b",
        "choices": [{"message": {"role": "assistant", "content": "A roofline is..."}}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 17, "total_tokens": 59},
    }

    def caller(body, streaming):
        assert not streaming
        return 200, json.dumps(resp).encode()

    out = P.process_non_streaming(_request(), caller, _cfg(), _sampler())
    r = out.record
    assert out.status == 200
    assert r["prompt_tokens"] == 42 and r["completion_tokens"] == 17
    assert r["tokens_exact"] == 1
    assert r["total_ms"] >= 0 and r["ttft_ms"] == r["total_ms"]
    assert r["kwh"] > 0 and r["local_cost_usd"] > 0
    assert r["cloud_cost_usd"] is not None and r["cloud_cost_usd"] > 0
    assert r["savings_pct"] is not None and r["savings_pct"] > 50


def test_non_streaming_without_usage_uses_heuristic():
    resp = {
        "choices": [{"message": {"role": "assistant", "content": "word " * 40}}]
    }

    def caller(body, streaming):
        return 200, json.dumps(resp).encode()

    r = P.process_non_streaming(_request(), caller, _cfg(), _sampler()).record
    assert r["tokens_exact"] == 0
    assert r["completion_tokens"] == 50  # "word " * 40 -> 200 chars // 4
    assert r["prompt_tokens"] > 0


def test_non_streaming_upstream_error_recorded():
    def caller(body, streaming):
        raise P.ProxyUpstreamError(503, "server busy")

    out = P.process_non_streaming(_request(), caller, _cfg(), _sampler())
    assert out.status == 503
    r = out.record
    assert r["status"] == 503 and "server busy" in r["error"]
    assert r["cloud_cost_usd"] is None


def test_streaming_forwards_all_bytes_and_counts_usage():
    import time

    def make_chunks():
        a = b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
        b = b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
        c = b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":11,"completion_tokens":2,"total_tokens":13}}\n\n'
        d = b"data: [DONE]\n\n"
        return [a, b, c, d]

    def caller(body, streaming):
        assert streaming
        time.sleep(0.01)
        return 200, iter(make_chunks())

    out = P.process_streaming(_request(stream=True), caller, _cfg(), _sampler())
    r = out.record
    assert out.status == 200
    joined = b"".join(out.chunks)
    assert joined.startswith(b"data:") and b"[DONE]" in joined
    assert r["prompt_tokens"] == 11 and r["completion_tokens"] == 2
    assert r["tokens_exact"] == 1
    assert r["streaming"] == 1
    assert r["ttft_ms"] is not None and r["ttft_ms"] <= r["total_ms"]
    assert r["tokens_per_s"] is not None


def test_streaming_without_usage_estimates_from_deltas():
    a = b'data: {"choices":[{"delta":{"content":"alpha beta gamma delta"}}]}\n\n'
    b = b"data: [DONE]\n\n"

    def caller(body, streaming):
        return 200, iter([a, b])

    r = P.process_streaming(_request(stream=True), caller, _cfg(), _sampler()).record
    assert r["tokens_exact"] == 0
    assert r["completion_tokens"] == 5  # "alpha beta gamma delta" = 22 chars -> 5


def test_streaming_upstream_error():
    def caller(body, streaming):
        raise P.ProxyUpstreamError(502, "unreachable")

    out = P.process_streaming(_request(stream=True), caller, _cfg(), _sampler())
    assert out.status == 502
    assert out.record["streaming"] == 1
    assert "unreachable" in out.record["error"]
