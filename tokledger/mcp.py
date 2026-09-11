"""Minimal MCP (Model Context Protocol) server over stdio.

``tokledger mcp`` exposes the ledger to MCP-aware coding agents as four
read-only tools:

* ``tokledger_stats``          - aggregate totals (requests, tokens, kWh, $, savings)
* ``tokledger_recent``         - last N ledger records
* ``tokledger_model_breakdown``- per-model rollup
* ``tokledger_cloud_savings``  - local vs cloud-equivalent cost

Implementation is a strict JSON-RPC 2.0 subset over stdin/stdout with
newline-delimited messages - the transport every MCP host uses. No
dependencies, no network.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from . import __version__, cost as costmod, ledger as ledgermod

PROTOCOL_VERSION = "2025-03-26"

_TOOLS = [
    {
        "name": "tokledger_stats",
        "description": (
            "Aggregate totals from the local LLM inference ledger: request count, "
            "prompt/completion tokens, average TTFT, energy (kWh), local cost ($), "
            "cloud-equivalent cost ($), and percent saved vs cloud."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "tokledger_recent",
        "description": "The most recent N ledger records (newest first).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "How many records (1-200)."}
            },
        },
    },
    {
        "name": "tokledger_model_breakdown",
        "description": "Per-model rollup: requests, tokens, avg TTFT, local and cloud-equivalent cost.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "tokledger_cloud_savings",
        "description": (
            "Local vs cloud cost comparison: total local $, total cloud-equivalent $, "
            "savings $ and %."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _tool_result(payload: Any) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str, indent=2)}],
        "isError": False,
    }


def _tool_error(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": f"error: {message}"}], "isError": True}


def handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process one JSON-RPC request; returns a response (or None for notifications)."""
    rid = req.get("id")
    method = str(req.get("method", ""))
    params = req.get("params") or {}
    is_notification = "id" not in req

    def reply(result: Any) -> Optional[Dict[str, Any]]:
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def fail(code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    if method == "initialize":
        return reply(
            {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "tokledger", "version": __version__},
            }
        )
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None
    if method == "tools/list":
        return reply({"tools": _TOOLS})

    if method == "tools/call":
        name = str(params.get("name", ""))
        args = params.get("arguments") or {}
        conn = ledgermod.connect()
        try:
            if name == "tokledger_stats":
                return reply(_tool_result(ledgermod.totals(conn)))
            if name == "tokledger_recent":
                limit = max(1, min(int(args.get("limit", 20)), 200))
                return reply(_tool_result(ledgermod.recent(conn, limit=limit)))
            if name == "tokledger_model_breakdown":
                return reply(_tool_result(ledgermod.by_model(conn)))
            if name == "tokledger_cloud_savings":
                t = ledgermod.totals(conn)
                local = t["local_cost_usd"]
                cloud = t["cloud_cost_usd"] or 0.0
                return reply(
                    _tool_result(
                        {
                            "local_cost_usd": local,
                            "cloud_equivalent_usd": cloud,
                            "saved_usd": round(cloud - local, 6),
                            "savings_pct": t["savings_pct"],
                            "priced_requests": t["priced_requests"],
                        }
                    )
                )
            return fail(-32602, f"unknown tool: {name}")
        finally:
            conn.close()

    if rid is not None or not is_notification:
        return fail(-32601, f"method not supported: {method}")
    return None


def serve_stdin() -> int:
    """Line-delimited JSON-RPC loop over stdin/stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {e}"}}
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, default=str) + "\n")
            sys.stdout.flush()
    return 0


def main() -> int:
    return serve_stdin()


__all__ = ["handle_request", "serve_stdin", "main", "_TOOLS"]
