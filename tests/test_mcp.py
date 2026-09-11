"""MCP server (in-process + subprocess)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tokledger import ledger as L
from tokledger import mcp


def test_initialize_and_tools_list(env):
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["serverInfo"]["name"] == "tokledger"
    assert resp["result"]["capabilities"]["tools"]

    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert "tokledger_stats" in names
    assert "tokledger_cloud_savings" in names


def test_notification_returns_none(env):
    assert mcp.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_call_stats_and_recent(env, conn):
    conn.execute(
        "INSERT INTO requests (ts, model, prompt_tokens, completion_tokens, total_tokens, local_cost_usd, cloud_cost_usd, status) "
        "VALUES (1700000000, 'mx', 10, 5, 15, 0.001, 0.5, 200)"
    )
    conn.commit()

    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                               "params": {"name": "tokledger_stats"}})
    text = json.loads(resp["result"]["content"][0]["text"])
    assert text["requests"] == 1

    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                               "params": {"name": "tokledger_recent", "arguments": {"limit": 5}}})
    rows = json.loads(resp["result"]["content"][0]["text"])
    assert len(rows) == 1 and rows[0]["model"] == "mx"

    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                               "params": {"name": "tokledger_cloud_savings"}})
    sv = json.loads(resp["result"]["content"][0]["text"])
    assert sv["cloud_equivalent_usd"] == 0.5
    assert sv["savings_pct"] is not None


def test_unknown_tool_error(env):
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                               "params": {"name": "nope"}})
    assert "error" in resp and resp["error"]["code"] == -32602


def test_mcp_over_stdio_subprocess(env):
    """Spawn `python -m tokledger mcp` and drive it over a pipe."""
    payload = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "tokledger_stats"}}),
        ]
    ) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "tokledger", "mcp"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**__import__("os").environ},
    )
    assert proc.returncode == 0
    lines = [json.loads(l) for l in proc.stdout.strip().splitlines()]
    ids = sorted(l["id"] for l in lines)
    assert ids == [1, 2, 3]
    by_id = {l["id"]: l for l in lines}
    assert by_id[1]["result"]["serverInfo"]["name"] == "tokledger"
    assert by_id[3]["result"]["content"][0]["text"]
