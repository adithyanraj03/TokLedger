"""CLI smoke tests (no network, no GPU)."""

from __future__ import annotations

import json
from pathlib import Path

from tokledger import cli


def test_cli_version():
    import pytest

    with pytest.raises(SystemExit) as ei:
        cli.main(["--version"])
    assert ei.value.code == 0


def test_cli_stats_empty(env, capsys):
    assert cli.main(["stats"]) == 0
    out = capsys.readouterr().out
    assert "requests:          0" in out


def test_cli_ingest_then_stats(env, capsys, tmp_path):
    f = tmp_path / "recs.jsonl"
    f.write_text(
        json.dumps({"model": "cli-model", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}) + "\n"
    )
    assert cli.main(["ingest", str(f)]) == 0
    out = capsys.readouterr().out
    assert "Ingested 1 record(s)" in out

    assert cli.main(["stats"]) == 0
    out = capsys.readouterr().out
    assert "requests:          1" in out
    assert "cli-model" not in out  # stats has no model names by design


def test_cli_export(env, capsys, tmp_path):
    f = tmp_path / "recs.jsonl"
    f.write_text(json.dumps({"model": "m", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}) + "\n")
    cli.main(["ingest", str(f)])
    out = tmp_path / "exp.jsonl"
    assert cli.main(["export", "-o", str(out)]) == 0
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["model"] == "m"


def test_cli_report(env, capsys, tmp_path):
    out = tmp_path / "report.html"
    assert cli.main(["report", "-o", str(out)]) == 0
    html = out.read_text()
    assert "TokLedger - Inference Report" in html
    assert "no data" in html


def test_cli_config_show_and_update(env, capsys):
    assert cli.main(["config"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert "usd_per_kwh" in shown

    assert cli.main(["config", "--usd-per-kwh", "0.25", "--client", "swarm"]) == 0
    updated = json.loads(capsys.readouterr().out)
    assert updated["usd_per_kwh"] == 0.25
    assert updated["client"] == "swarm"


def test_cli_ingest_missing_file(env, capsys):
    assert cli.main(["ingest", "does-not-exist.jsonl"]) != 0
