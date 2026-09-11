"""Static HTML report renderer.

``tokledger report`` produces a self-contained HTML file (same visual
language as the dashboard) with totals, per-day table, per-model table,
and the most recent requests. Suitable for emailing or attaching to a
research log.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import __version__, cost as costmod, ledger as ledgermod

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 40px 56px; background: #0b0e14; color: #d6dae3;
       font: 15px/1.55 "Segoe UI", system-ui, -apple-system, sans-serif; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 30px 0 12px; color: #9fb4ff; text-transform: uppercase; letter-spacing: 1.4px; }
.sub { color: #7a8194; margin: 0 0 24px; }
.roof { display: flex; gap: 30px; flex-wrap: wrap; background: #11151f;
        border: 1px solid #1f2534; border-radius: 10px; padding: 16px 20px; margin-bottom: 8px; }
.roof .k { color: #7a8194; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
.roof .v { font-size: 20px; font-weight: 600; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #1c2230; }
th { color: #7a8194; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.footer { margin-top: 36px; color: #555c6e; font-size: 13px; }
"""


def render(out_path: Optional[Path] = None) -> Path:
    from .config import data_dir

    out = Path(out_path) if out_path else data_dir() / "report.html"
    conn = ledgermod.connect()
    try:
        stats = ledgermod.totals(conn)
        days = ledgermod.by_day(conn)
        models = ledgermod.by_model(conn)
        recent = ledgermod.recent(conn, limit=30)
    finally:
        conn.close()

    e = html.escape
    cards = (
        f'<div class="roof">'
        f'<div><div class="k">requests</div><div class="v">{stats["requests"]}</div></div>'
        f'<div><div class="k">tokens</div><div class="v">{stats["total_tokens"]:,}</div></div>'
        f'<div><div class="k">energy</div><div class="v">{stats["kwh"]:.4f} kWh</div></div>'
        f'<div><div class="k">local cost</div><div class="v">{costmod.fmt_usd(stats["local_cost_usd"])}</div></div>'
        f'<div><div class="k">cloud-equivalent</div><div class="v">{costmod.fmt_usd(stats["cloud_cost_usd"])}</div></div>'
        f'<div><div class="k">saved vs cloud</div><div class="v">'
        + (f'{stats["savings_pct"]:.1f} %' if stats["savings_pct"] is not None else "-")
        + "</div></div></div>"
    )

    day_rows = "".join(
        f'<tr><td>{e(d["day"])}</td><td class="num">{d["requests"]}</td>'
        f'<td class="num">{(d["total_tokens"] or 0):,}</td>'
        f'<td class="num">{costmod.fmt_usd(d["local_cost_usd"])}</td>'
        f'<td class="num">{costmod.fmt_usd(d["cloud_cost_usd"])}</td></tr>'
        for d in days
    ) or '<tr><td colspan="5" style="color:#555c6e">no data</td></tr>'

    model_rows = "".join(
        f'<tr><td>{e(m["model"])}</td><td class="num">{m["requests"]}</td>'
        f'<td class="num">{(m["total_tokens"] or 0):,}</td>'
        f'<td class="num">{m["avg_ttft_ms"] and f"{m[chr(34)+chr(34)]}" if False else f"{m['avg_ttft_ms']:.0f} ms"}</td>'
        f'<td class="num">{costmod.fmt_usd(m["local_cost_usd"])}</td>'
        f'<td class="num">{costmod.fmt_usd(m["cloud_cost_usd"])}</td></tr>'
        for m in models
    ) or '<tr><td colspan="6" style="color:#555c6e">no data</td></tr>'

    recent_rows = "".join(
        f'<tr><td>{e(datetime.fromtimestamp(r["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M"))}</td>'
        f'<td>{e(r["model"])}</td>'
        f'<td class="num">{r["prompt_tokens"]:,}</td>'
        f'<td class="num">{r["completion_tokens"]:,}</td>'
        f'<td class="num">{(f"{r["ttft_ms"]:.0f} ms" if r["ttft_ms"] is not None else "-")}</td>'
        f'<td class="num">{costmod.fmt_usd(r["local_cost_usd"])}</td>'
        f'<td class="num">{costmod.fmt_usd(r["cloud_cost_usd"])}</td>'
        f'<td>{e(r["status"])}</td></tr>'
        for r in recent
    ) or '<tr><td colspan="8" style="color:#555c6e">no data</td></tr>'

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    doc = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>TokLedger - Report</title>
<style>{_CSS}</style></head>
<body>
<h1>TokLedger - Inference Report</h1>
<p class="sub">Local vs cloud-equivalent cost of every request on your rig &middot; {now}</p>
{cards}
<h2>Daily breakdown</h2>
<table><tr><th>day</th><th class="num">requests</th><th class="num">tokens</th>
<th class="num">local $</th><th class="num">cloud-equiv $</th></tr>{day_rows}</table>
<h2>By model</h2>
<table><tr><th>model</th><th class="num">requests</th><th class="num">tokens</th>
<th class="num">avg TTFT</th><th class="num">local $</th><th class="num">cloud-equiv $</th></tr>{model_rows}</table>
<h2>Recent requests (latest 30)</h2>
<table><tr><th>time (UTC)</th><th>model</th><th class="num">prompt</th><th class="num">completion</th>
<th class="num">TTFT</th><th class="num">local $</th><th class="num">cloud $</th><th class="num">status</th></tr>{recent_rows}</table>
<div class="footer">TokLedger {__version__} &middot; generated by <code>tokledger report</code></div>
</body>
</html>
"""
    out.write_text(doc, encoding="utf-8")
    return out
