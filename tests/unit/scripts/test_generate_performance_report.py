import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.performance import ResolutionRecord
from scripts.generate_performance_report import _parse_as_of, main
from trading.ledger import PaperLedger

_ROOT = Path(__file__).resolve().parents[3]


def _record(signal_id: str = "sig-1") -> ResolutionRecord:
    return ResolutionRecord(
        signal_id=signal_id,
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        entry=100.0,
        stop=90.0,
        target=120.0,
        created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
        exit_price=120.0,
        exit_reason="target",
        candles_used=4,
        resolver_version="paper-resolution-v1",
    )


def test_the_as_of_parser_defaults_to_utc():
    parsed = _parse_as_of("2026-10-20T12:00:00")

    assert parsed == datetime(2026, 10, 20, 12, tzinfo=UTC)


def test_the_as_of_parser_keeps_an_explicit_offset():
    parsed = _parse_as_of("2026-10-20T12:00:00+02:00")

    assert parsed == datetime(2026, 10, 20, 10, tzinfo=UTC)


async def _seed(ledger_path: Path) -> None:
    ledger = PaperLedger(ledger_path)
    await ledger.record_resolution(_record())


def test_the_script_writes_a_report_and_prints_the_data_hash(tmp_path, monkeypatch, capsys):
    ledger_path = tmp_path / "paper_ledger.db"
    output = tmp_path / "performance" / "report.json"
    asyncio.run(_seed(ledger_path))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_performance_report.py",
            "--as-of",
            "2026-10-20T12:00:00+00:00",
            "--output",
            str(output),
            "--ledger",
            str(ledger_path),
        ],
    )
    monkeypatch.chdir(_ROOT)

    main()

    payload = json.loads(output.read_text(encoding="utf-8"))
    printed = capsys.readouterr().out.strip()

    assert payload["report_version"] == "performance-report-v2"
    assert payload["mode"] == "paper"
    assert payload["total_resolved"] == 1
    assert payload["status"] == "insufficient_sample"
    assert printed == payload["data_hash"]


def test_the_script_writes_a_report_for_an_empty_ledger(tmp_path, monkeypatch, capsys):
    output = tmp_path / "performance" / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_performance_report.py",
            "--as-of",
            "2026-10-20T12:00:00+00:00",
            "--output",
            str(output),
            "--ledger",
            str(tmp_path / "empty.db"),
        ],
    )
    monkeypatch.chdir(_ROOT)

    main()

    payload = json.loads(output.read_text(encoding="utf-8"))
    printed = capsys.readouterr().out.strip()

    assert payload["status"] == "no_trades"
    assert payload["total_resolved"] == 0
    assert printed == payload["data_hash"]


def test_the_script_output_has_no_nan_and_no_infinity(tmp_path, monkeypatch, capsys):
    ledger_path = tmp_path / "paper_ledger.db"
    output = tmp_path / "performance" / "report.json"
    asyncio.run(_seed(ledger_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_performance_report.py",
            "--as-of",
            "2026-10-20T12:00:00+00:00",
            "--output",
            str(output),
            "--ledger",
            str(ledger_path),
        ],
    )
    monkeypatch.chdir(_ROOT)

    main()

    raw = output.read_text(encoding="utf-8")
    assert "NaN" not in raw
    assert "Infinity" not in raw


def test_the_script_rejects_an_invalid_as_of(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["generate_performance_report.py", "--as-of", "not-a-timestamp"]
    )

    with pytest.raises(ValueError):
        _parse_as_of("not-a-timestamp")
