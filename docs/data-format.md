# Data Format

All TokLedger state lives in one directory (default `~/.tokledger`;
override with `$TOKLEDGER_DATA`):

| File | Purpose |
| :--- | :--- |
| `ledger.db` | SQLite ledger (`requests` table, one row per LLM request) |
| `config.json` | user-editable configuration (see below) |

## `requests` columns

| Column | Type | Meaning |
| :--- | :--- | :--- |
| `ts` | REAL | unix epoch (UTC) of request start |
| `model` | TEXT | model name as requested |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | INTEGER | exact when `tokens_exact = 1`, heuristic otherwise |
| `tokens_exact` | INTEGER | 1 = engine-reported usage, 0 = estimated |
| `ttft_ms` | REAL | time to first token (streaming) or full latency (non-streaming) |
| `total_ms` | REAL | end-to-end latency |
| `tokens_per_s` | REAL | completion tokens / total seconds |
| `kwh`, `watts`, `power_mode` | REAL/REAL/TEXT | energy attribution (`nvml` = sampled draw, `static` = configured draw) |
| `local_cost_usd` | REAL | `kwh * usd_per_kwh` |
| `cloud_cost_usd` | REAL | cloud-equivalent at the reference price (NULL = unknown price) |
| `savings_pct` | REAL | `(1 - local/cloud) * 100` |
| `streaming` | INTEGER | 0/1 |
| `status` | INTEGER | upstream HTTP status |
| `error` | TEXT | error detail on failures |
| `client` | TEXT | configured client tag |
| `preview` | TEXT | first 200 chars of the first user message |

## `config.json`

```json
{
  "upstream": "http://127.0.0.1:8080/v1",
  "idle_watts": 20.0,
  "load_watts": 300.0,
  "usd_per_kwh": 0.15,
  "cloud_reference_model": "gpt-4o-mini",
  "cloud_prices": {
    "gpt-4o-mini": { "input": 0.15, "output": 0.60 },
    "gpt-4o": { "input": 2.50, "output": 10.00 }
  },
  "client": "tokledger"
}
```

* `upstream` - the local OpenAI-compatible endpoint the proxy forwards to
  (`http://127.0.0.1:8080/v1` for llama.cpp server,
  `http://127.0.0.1:11434/v1` for Ollama, `http://127.0.0.1:1234/v1` for
  LM Studio). Set via `tokledger serve --upstream URL` or by editing the file.
* `idle_watts` / `load_watts` - power model used when NVML is unavailable.
* `usd_per_kwh` - your electricity rate.
* `cloud_reference_model` - which price-list entry the "cloud-equivalent"
  column is computed against.
* `cloud_prices` - USD per 1M tokens, editable; merged over defaults.
* `client` - tag written to every record (handy when several apps share the
  proxy; also settable per-deployment).

## JSONL export / ingest format

`tokledger export` (and `GET /export.jsonl`) writes one JSON object per
line with every column above. `tokledger ingest` accepts:

1. full TokLedger export lines, and
2. minimal OpenAI-style lines - `{"model": "...", "usage":
   {"prompt_tokens": N, "completion_tokens": M}}` with an optional `"ts"`.

Malformed lines are skipped and reported.

## Token counting

* exact counts are taken from the engine's `usage` block when present
  (Ollama always; llama.cpp with `--jinja` and stream usage; vLLM with
  `stream_options.include_usage`);
* otherwise a deterministic heuristic (~4 chars/token with a word-count
  floor) is used and the record is marked `tokens_exact = 0` (shown as
  "est" in the dashboard).
