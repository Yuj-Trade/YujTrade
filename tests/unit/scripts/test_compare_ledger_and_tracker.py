import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.performance import ResolutionRecord
from scripts.compare_ledger_and_tracker import main
from trading.ledger import PaperLedger

_ROOT = Path(__file__).resolve().parents[3]
PRICED_COUNT = 30


def _record(signal_id: str, exit_reason: str, exit_price: float | None) -> ResolutionRecord:
    return ResolutionRecord(
        signal_id=signal_id,
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        entry=100.0,
        stop=90.0,
        target=120.0,
        created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC) if exit_reason != "no_data" else None,
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="paper-resolution-v1",
    )


async def _seed(ledger_path: Path) -> None:
    ledger = PaperLedger(ledger_path)
    for index in range(PRICED_COUNT):
        await ledger.record_resolution(_record(f"sig-{index}", "target", 120.0))
    await ledger.record_resolution(_record("sig-nd", "no_data", None))


def _write_tracker(path: Path) -> None:
    history = {f"sig-{index}": {"outcome": True, "details": {}} for index in range(PRICED_COUNT)}
    history["sig-nd"] = {"outcome": None, "details": {"resolution_status": "no_data"}}
    history["sig-pending"] = {"outcome": None, "details": {}}
    path.write_text(json.dumps(history), encoding="utf-8")


def _run(monkeypatch, ledger: Path, tracker: Path, snapshot: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare_ledger_and_tracker.py",
            "--ledger",
            str(ledger),
            "--tracker",
            str(tracker),
            "--snapshot",
            str(snapshot),
        ],
    )
    monkeypatch.chdir(_ROOT)
    main()


def test_the_comparison_accepts_a_consistent_ledger_and_tracker(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "paper_ledger.db"
    tracker = tmp_path / "signal_history.json"
    snapshot = tmp_path / "ledger_row_count.json"
    asyncio.run(_seed(ledger))
    _write_tracker(tracker)

    _run(monkeypatch, ledger, tracker, snapshot)

    output = capsys.readouterr().out
    assert f"ledger rows: {PRICED_COUNT + 1} (priced {PRICED_COUNT}, no_data 1)" in output
    assert "OK: the ledger and the tracker agree" in output


def test_the_comparison_reports_a_missing_tracker_resolution(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "paper_ledger.db"
    tracker = tmp_path / "signal_history.json"
    snapshot = tmp_path / "ledger_row_count.json"
    asyncio.run(_seed(ledger))
    tracker.write_text(json.dumps({}), encoding="utf-8")

    with pytest.raises(SystemExit):
        _run(monkeypatch, ledger, tracker, snapshot)

    output = capsys.readouterr().out
    assert "FAIL: the tracker holds 0 resolved signals" in output


def test_the_comparison_reports_a_high_no_data_ratio(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "paper_ledger.db"
    tracker = tmp_path / "signal_history.json"
    snapshot = tmp_path / "ledger_row_count.json"
    asyncio.run(_seed(ledger))
    _write_tracker(tracker)
    connection = sqlite3.connect(ledger)
    try:
        for index in range(20):
            connection.execute(
                "INSERT INTO signal_resolutions(signal_id, symbol, timeframe, side, entry, stop, "
                "target, created_at_utc, exit_at_utc, exit_price, exit_reason, candles_used, "
                "resolver_version, recorded_at_utc) VALUES (?, 'BTC/USDT', '1h', 'buy', 100, 90, "
                "120, '2026-10-01T10:00:00.000000+00:00', NULL, NULL, 'no_data', 0, 'v1', "
                "'2026-10-01T10:00:00.000000+00:00')",
                (f"sig-nd-{index}",),
            )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SystemExit):
        _run(monkeypatch, ledger, tracker, snapshot)

    output = capsys.readouterr().out
    assert "the no_data ratio is" in output
    assert "above the 5% limit" in output


def test_the_comparison_detects_a_shrinking_ledger(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "paper_ledger.db"
    tracker = tmp_path / "signal_history.json"
    snapshot = tmp_path / "ledger_row_count.json"
    asyncio.run(_seed(ledger))
    _write_tracker(tracker)
    snapshot.write_text(json.dumps({"rows": 99}), encoding="utf-8")

    with pytest.raises(SystemExit):
        _run(monkeypatch, ledger, tracker, snapshot)

    output = capsys.readouterr().out
    assert "the ledger row count fell from 99 to" in output
    assert "must never be pruned" in output


def test_the_comparison_survives_a_missing_ledger(tmp_path, monkeypatch, capsys):
    tracker = tmp_path / "signal_history.json"
    snapshot = tmp_path / "ledger_row_count.json"
    _write_tracker(tracker)

    _run(monkeypatch, tmp_path / "missing.db", tracker, snapshot)

    output = capsys.readouterr().out
    assert "ledger rows: 0" in output
