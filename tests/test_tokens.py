"""Token counting."""

from __future__ import annotations

from tokledger import tokens as tok


def test_empty():
    assert tok.count_tokens("") == 0


def test_monotonic():
    short = "hello world"
    long = short + " and this keeps going for a long time with more words"
    assert tok.count_tokens(long) > tok.count_tokens(short)


def test_deterministic():
    t = "The quick brown fox jumps over the lazy dog. " * 10
    assert tok.count_tokens(t) == tok.count_tokens(t)


def test_prompt_tokens_counts_messages():
    msgs = [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "Explain rooflines in two sentences. " * 4},
    ]
    n = tok.count_prompt_tokens(msgs)
    assert n > 0
    assert n > tok.count_tokens("Explain rooflines in two sentences. ")


def test_prompt_tokens_multi_part_content():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "word " * 20}]}]
    assert tok.count_prompt_tokens(msgs) > 0


def test_parse_usage():
    assert tok.parse_usage({"usage": {"prompt_tokens": 3, "completion_tokens": 7}}) == (3, 7)
    assert tok.parse_usage({"usage": {}}) is None
    assert tok.parse_usage({}) is None
    assert tok.parse_usage("nope") is None


def test_usage_from_sse_chunks_finds_last():
    chunks = [
        {"choices": [{"delta": {"content": "a"}}]},
        {"choices": [{"delta": {"content": "b"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
    ]
    assert tok.usage_from_sse_chunks(chunks) == (5, 2)


def test_completion_from_deltas():
    deltas = ["Hello ", {"content": "world"}, "again"]
    assert tok.completion_tokens_from_deltas(deltas) >= 2


def test_first_message_preview():
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "x" * 500}]
    assert len(tok.first_message_preview(msgs)) == 200
    assert tok.first_message_preview([{"role": "user", "content": "hi"}]) == "hi"
    assert tok.first_message_preview(None) == ""
