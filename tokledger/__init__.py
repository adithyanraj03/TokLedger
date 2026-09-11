"""TokLedger - the local inference ledger.

Zero dependencies, no cloud, no account. Point any OpenAI-compatible local
server (Ollama, llama.cpp, LM Studio, vLLM) through TokLedger and every
request is priced:

* tokens (exact when the engine reports usage, heuristic otherwise)
* TTFT and end-to-end latency, tokens/s
* energy (kWh, from NVML power sampling when available, else a
  configurable draw) and local $ at your electricity rate
* the cloud-equivalent $ at a reference API price list

Everything lands in one SQLite file with a zero-dependency dashboard,
static HTML reports, JSONL export, and an MCP server that exposes the
ledger to coding agents.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
