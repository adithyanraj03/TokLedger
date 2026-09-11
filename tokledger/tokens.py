"""Token counting.

Engines that report ``usage`` (Ollama, llama.cpp with
``stream_options.include_usage``, vLLM) give exact counts - we always prefer
those. When usage is absent we fall back to a deterministic heuristic:
~4 characters per token, with a words-based lower bound (GPT-family
tokenizers average 3.5-4.5 chars/token for English code-and-prose).

The heuristic is *deterministic* so the ledger is reproducible, and it is
labelled as an estimate in the UI.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def count_tokens(text: str) -> int:
    """Deterministic token estimate for a text string."""
    if not text:
        return 0
    chars = len(text)
    words = len(text.split())
    # ~4 chars/token blended with a word bound (~0.75 tokens/word)
    return max(1, chars // 4, int(words * 0.75))


def count_prompt_tokens(messages: Any) -> int:
    """Estimate prompt tokens from an OpenAI-style messages list.

    Adds a small per-message overhead (role + delimiter tokens).
    """
    total = 0
    if not isinstance(messages, list):
        return total
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            total += count_tokens(content) + 4
        elif isinstance(content, list):
            # multi-part content (e.g. [{"type": "text", "text": "..."}])
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    total += count_tokens(part["text"])
            total += 4
    return total


def parse_usage(obj: Any) -> Optional[Tuple[int, int]]:
    """Extract (prompt_tokens, completion_tokens) from an API response.

    Returns None when the response carries no usable usage block.
    """
    if not isinstance(obj, dict):
        return None
    usage = obj.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if not isinstance(prompt, (int, float)) or not isinstance(completion, (int, float)):
        return None
    return int(prompt), int(completion)


def usage_from_sse_chunks(chunks: list) -> Optional[Tuple[int, int]]:
    """Find the last usage block in parsed SSE JSON chunks (streaming).

    llama.cpp and vLLM emit a final chunk carrying ``usage`` when
    ``stream_options: {"include_usage": true}``.
    """
    found = None
    for chunk in chunks:
        found = parse_usage(chunk) or found
    return found


def completion_tokens_from_deltas(deltas: Any) -> int:
    """Fallback: estimate completion tokens from streamed delta text."""
    parts = []
    if isinstance(deltas, str):
        parts.append(deltas)
    elif isinstance(deltas, list):
        for d in deltas:
            if isinstance(d, str):
                parts.append(d)
            elif isinstance(d, dict) and isinstance(d.get("content"), str):
                parts.append(d["content"])
    return count_tokens("".join(parts))


def first_message_preview(messages: Any, limit: int = 200) -> str:
    """Short preview of the user's first message (for the dashboard)."""
    if not isinstance(messages, list):
        return ""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content[:limit]
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        return part["text"][:limit]
    return ""
