"""TokLedger command-line interface.

    tokledger serve --port 8081 --upstream http://127.0.0.1:8080/v1
        proxy + API + dashboard in one process (the normal setup)
    tokledger dashboard --port 8090
        API + dashboard only (the proxy runs elsewhere)
    tokledger mock --port 8999
        deterministic offline OpenAI-compatible provider
    tokledger stats
        print aggregate totals
    tokledger report [-o out.html]
        render a static HTML report
    tokledger ingest file.jsonl
        import records
    tokledger export [-o file.jsonl]
        dump the full ledger
    tokledger mcp
        run the MCP stdio server
    tokledger config [--idle-watts N --load-watts N --usd-per-kwh N --client NAME]
        show/update configuration
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__, cost as costmod, ingest as ingestmod, ledger as ledgermod, report as reportmod
from .config import data_dir, load_config, save_config, update_config


def _cmd_serve(args) -> int:
    if args.upstream:
        cfg = load_config()
        cfg["upstream"] = args.upstream
        save_config(cfg)
    from .server import run_server

    srv = run_server(args.port, host=args.host, upstream=args.upstream, proxy=not args.no_proxy)
    print(f"TokLedger {__version__} listening on http://{args.host}:{args.port}")
    print(f"  dashboard:  http://{args.host}:{args.port}/")
    print(f"  API:        http://{args.host}:{args.port}/api/stats")
    if not args.no_proxy:
        print(f"  proxy:      http://{args.host}:{args.port}/v1/chat/completions")
    print(f"  data dir:   {data_dir()}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


def _cmd_dashboard(args) -> int:
    from .server import run_server

    srv = run_server(args.port, host=args.host, proxy=False)
    print(f"TokLedger dashboard on http://{args.host}:{args.port} (proxy disabled)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


def _cmd_mock(args) -> int:
    from .mock import run

    srv = run(args.port, host=args.host)
    print(f"TokLedger mock provider on http://{args.host}:{args.port}/v1")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


def _cmd_stats(args) -> int:
    conn = ledgermod.connect()
    try:
        t = ledgermod.totals(conn)
    finally:
        conn.close()
    lines = [
        f"requests:          {t['requests']}",
        f"prompt tokens:     {t['prompt_tokens']:,}",
        f"completion tokens: {t['completion_tokens']:,}",
        f"total tokens:      {t['total_tokens']:,}",
        f"avg TTFT:          {(f'{t['avg_ttft_ms']:.0f} ms' if t['avg_ttft_ms'] is not None else '-')}",
        f"avg total time:    {(f'{t['avg_total_ms'] / 1000:.2f} s' if t['avg_total_ms'] is not None else '-')}",
        f"energy:            {t['kwh']:.6f} kWh",
        f"local cost:        {costmod.fmt_usd(t['local_cost_usd'])}",
        f"cloud-equivalent:  {costmod.fmt_usd(t['cloud_cost_usd'])} (of {t['priced_requests']} priced requests)",
        f"savings vs cloud:  {(f'{t['savings_pct']:.1f} %' if t['savings_pct'] is not None else '-')}",
    ]
    print("\n".join(lines))
    return 0


def _cmd_report(args) -> int:
    out = reportmod.render(out_path=args.output)
    print(f"Report written to {out}")
    return 0


def _cmd_ingest(args) -> int:
    cfg = load_config()
    conn = ledgermod.connect()
    try:
        inserted, skipped = ingestmod.ingest_file(args.file, conn, cfg)
    except FileNotFoundError:
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Ingested {inserted} record(s); skipped {skipped}.")
    return 0 if inserted + skipped > 0 else 1


def _cmd_export(args) -> int:
    import pathlib

    conn = ledgermod.connect()
    try:
        out = pathlib.Path(args.output) if args.output else pathlib.Path.cwd() / "tokledger-export.jsonl"
        n = ledgermod.export_jsonl(conn, out)
    finally:
        conn.close()
    print(f"Exported {n} record(s) to {out}")
    return 0


def _cmd_mcp(args) -> int:
    from . import mcp

    print(f"TokLedger MCP server (v{__version__}) - stdio transport; ledger at {data_dir() / 'ledger.db'}", file=sys.stderr)
    return mcp.serve_stdin()


def _cmd_config(args) -> int:
    if not any(v is not None for v in (args.idle_watts, args.load_watts, args.usd_per_kwh, args.client, args.reference, args.upstream)):
        print(json.dumps(load_config(), indent=2))
        return 0
    kwargs = {}
    if args.idle_watts is not None:
        kwargs["idle_watts"] = args.idle_watts
    if args.load_watts is not None:
        kwargs["load_watts"] = args.load_watts
    if args.usd_per_kwh is not None:
        kwargs["usd_per_kwh"] = args.usd_per_kwh
    if args.client is not None:
        kwargs["client"] = args.client
    if args.reference is not None:
        kwargs["cloud_reference_model"] = args.reference
    if args.upstream is not None:
        kwargs["upstream"] = args.upstream
    cfg = update_config(**kwargs)
    print(json.dumps(cfg, indent=2))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="tokledger", description="The local inference ledger.")
    p.add_argument("--version", action="version", version=f"tokledger {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="proxy + API + dashboard (default)")
    s.add_argument("--port", type=int, default=8081)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--upstream", default=None, help="e.g. http://127.0.0.1:8080/v1")
    s.add_argument("--no-proxy", action="store_true", help="disable the proxy route")
    s.set_defaults(fn=_cmd_serve)

    d = sub.add_parser("dashboard", help="API + dashboard only")
    d.add_argument("--port", type=int, default=8090)
    d.add_argument("--host", default="127.0.0.1")
    d.set_defaults(fn=_cmd_dashboard)

    m = sub.add_parser("mock", help="deterministic offline OpenAI-compatible provider")
    m.add_argument("--port", type=int, default=8999)
    m.add_argument("--host", default="127.0.0.1")
    m.set_defaults(fn=_cmd_mock)

    st = sub.add_parser("stats", help="print aggregate totals")
    st.set_defaults(fn=_cmd_stats)

    r = sub.add_parser("report", help="render static HTML report")
    r.add_argument("-o", "--output", default=None)
    r.set_defaults(fn=_cmd_report)

    i = sub.add_parser("ingest", help="import JSONL records")
    i.add_argument("file")
    i.set_defaults(fn=_cmd_ingest)

    x = sub.add_parser("export", help="export the full ledger")
    x.add_argument("-o", "--output", default=None)
    x.set_defaults(fn=_cmd_export)

    mc = sub.add_parser("mcp", help="run the MCP stdio server")
    mc.set_defaults(fn=_cmd_mcp)

    c = sub.add_parser("config", help="show/update configuration")
    c.add_argument("--idle-watts", type=float, default=None)
    c.add_argument("--load-watts", type=float, default=None)
    c.add_argument("--usd-per-kwh", type=float, default=None)
    c.add_argument("--client", default=None)
    c.add_argument("--reference", default=None, help="cloud reference model for pricing")
    c.add_argument("--upstream", default=None)
    c.set_defaults(fn=_cmd_config)

    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        # default: serve
        args = p.parse_args(["serve"])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
