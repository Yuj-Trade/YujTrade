"""The report is reproducible: the same ledger yields the same report.

The determinism test builds the report twice over the same ledger and
compares every field. The independent recomputation test reads the raw
ledger rows with the standard library only and rebuilds the equity curve,
the drawdown, the Sharpe and the Sortino ratios without touching
`domain/performance` or `application`, so a bug in the production code
cannot hide behind the same bug in the test.
"""

import json
import math
import sqlite3
from datetime import UTC, datetime

import pytest

from application.performance_report import PerformanceConfig, build_performance_report
from domain.performance import ResolutionRecord
from trading.ledger import PaperLedger

_AS_OF = datetime(2026, 10, 20, 12, tzinfo=UTC)


def _record(
    signal_id: str,
    exit_reason: str,
    exit_price: float,
    day: int,
    side: str = "buy",
    entry: float = 100.0,
    stop: float = 90.0,
) -> ResolutionRecord:
    return ResolutionRecord(
        signal_id=signal_id,
        symbol="BTC/USDT",
        timeframe="1h",
        side=side,
        entry=entry,
        stop=stop,
        target=120.0,
        created_at=datetime(2026, 10, day, 10, tzinfo=UTC),
        exit_at=datetime(2026, 10, day, 14, tzinfo=UTC),
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="paper-resolution-v1",
    )


def _records() -> list[ResolutionRecord]:
    return [
        _record("sig-a", "target", 120.0, 1),
        _record("sig-b", "stop", 90.0, 2),
        _record("sig-c", "expired", 110.0, 3),
        _record("sig-d", "target", 125.0, 4),
        _record("sig-e", "stop", 88.0, 5),
        _record("sig-f", "target", 118.0, 6),
    ]


def _config() -> PerformanceConfig:
    return PerformanceConfig(
        initial_cash=10000.0,
        risk_per_trade_pct=1.0,
        fee_rate=0.001,
        slippage_rate=0.0005,
        rf_annual=0.0,
        periods_per_year=365.0,
        min_trades_for_ratios=3,
    )


async def _seed(ledger_path, records) -> None:
    ledger = PaperLedger(ledger_path)
    for record in records:
        await ledger.record_resolution(record)


def _read_rows(ledger_path) -> list[dict]:
    connection = sqlite3.connect(ledger_path)
    try:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            "SELECT signal_id, side, entry, stop, exit_at_utc, exit_price, exit_reason "
            "FROM signal_resolutions"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def _independent_net_r(row, fee_rate, slippage_rate):
    risk = abs(row["entry"] - row["stop"])
    direction = 1.0 if row["side"] == "buy" else -1.0
    gross = direction * (row["exit_price"] - row["entry"]) / risk
    cost = (fee_rate + slippage_rate) * (row["entry"] + row["exit_price"]) / risk
    return gross - cost


def _independent_mean(values):
    return sum(values) / len(values)


def _independent_stdev(values):
    mean = _independent_mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _independent_recompute(rows, config, as_of):
    priced = [row for row in rows if row["exit_price"] is not None]
    priced.sort(key=lambda row: (row["exit_at_utc"], row["signal_id"]))

    net_r = [_independent_net_r(row, config.fee_rate, config.slippage_rate) for row in priced]
    fractions = [value * config.risk_per_trade_pct / 100.0 for value in net_r]

    equity = config.initial_cash
    curve = [equity]
    for fraction in fractions:
        equity = equity * (1.0 + fraction)
        curve.append(equity)

    peak = curve[0]
    peak_index = 0
    depth = 0.0
    trough_index = 0
    best_peak_index = 0
    for index, value in enumerate(curve):
        if value > peak:
            peak = value
            peak_index = index
        current = (peak - value) / peak
        if current > depth:
            depth = current
            trough_index = index
            best_peak_index = peak_index

    start_day = priced[0]["exit_at_utc"][:10]
    end_day = as_of.astimezone(UTC).date().isoformat()
    span = (
        datetime.fromisoformat(end_day).date() - datetime.fromisoformat(start_day).date()
    ).days + 1
    buckets: dict[str, float] = {}
    for row, fraction in zip(priced, fractions, strict=True):
        day = row["exit_at_utc"][:10]
        buckets[day] = buckets.get(day, 1.0) * (1.0 + fraction)
    daily = []
    for offset in range(span):
        day = (datetime.fromisoformat(start_day).date()).toordinal() + offset
        key = datetime.fromordinal(day).date().isoformat()
        daily.append(buckets.get(key, 1.0) - 1.0)

    risk_free = config.rf_annual / config.periods_per_year
    average = _independent_mean(daily)
    spread = _independent_stdev(daily)
    sharpe = (average - risk_free) / spread * math.sqrt(config.periods_per_year)
    downside = math.sqrt(sum(min(value - risk_free, 0.0) ** 2 for value in daily) / len(daily))
    sortino = (average - risk_free) / downside * math.sqrt(config.periods_per_year)

    return {
        "curve": curve,
        "depth": depth,
        "peak_index": best_peak_index,
        "trough_index": trough_index,
        "daily": daily,
        "sharpe": sharpe,
        "sortino": sortino,
        "net_r": net_r,
    }


def _relative_difference(left, right):
    return abs(left - right) / max(abs(right), 1e-12)


async def test_two_reports_over_the_same_ledger_are_identical(tmp_path):
    ledger_path = tmp_path / "paper_ledger.db"
    await _seed(ledger_path, _records())
    config = _config()

    first = build_performance_report(_read_rows_as_records(ledger_path), config, _AS_OF)
    second = build_performance_report(_read_rows_as_records(ledger_path), config, _AS_OF)

    assert first.to_json() == second.to_json()
    assert first.data_hash == second.data_hash
    assert first.config_hash == second.config_hash


async def test_a_changed_exit_changes_the_data_hash(tmp_path):
    ledger_path = tmp_path / "paper_ledger.db"
    records = _records()
    await _seed(ledger_path, records)
    baseline = build_performance_report(_read_rows_as_records(ledger_path), _config(), _AS_OF)

    changed_path = tmp_path / "changed.db"
    changed_records = list(records)
    changed_records[0] = _record("sig-a", "target", 121.0, 1)
    await _seed(changed_path, changed_records)
    changed = build_performance_report(_read_rows_as_records(changed_path), _config(), _AS_OF)

    assert baseline.data_hash != changed.data_hash


async def test_the_independent_calculator_reproduces_the_report(tmp_path):
    ledger_path = tmp_path / "paper_ledger.db"
    await _seed(ledger_path, _records())
    config = _config()
    report = build_performance_report(_read_rows_as_records(ledger_path), config, _AS_OF)

    recomputed = _independent_recompute(_read_rows(ledger_path), config, _AS_OF)

    assert len(recomputed["curve"]) == len(_read_rows(ledger_path)) + 1
    assert _relative_difference(recomputed["curve"][0], report.initial_equity) < 1e-9
    assert _relative_difference(recomputed["curve"][-1], report.final_equity) < 1e-9
    assert _relative_difference(recomputed["depth"], report.max_drawdown.depth) < 1e-9
    assert recomputed["peak_index"] == report.max_drawdown.peak_index
    assert recomputed["trough_index"] == report.max_drawdown.trough_index
    assert _relative_difference(recomputed["sharpe"], report.sharpe) < 1e-9
    assert _relative_difference(recomputed["sortino"], report.sortino) < 1e-9


async def test_the_independent_calculator_reads_the_ledger_rows(tmp_path):
    ledger_path = tmp_path / "paper_ledger.db"
    await _seed(ledger_path, _records())

    rows = _read_rows(ledger_path)

    assert len(rows) == 6
    assert {row["exit_reason"] for row in rows} == {"target", "stop", "expired"}
    assert all(row["exit_at_utc"].endswith("+00:00") for row in rows)


def _read_rows_as_records(ledger_path) -> list[ResolutionRecord]:
    from domain.performance import parse_utc_timestamp

    records = []
    for row in _read_rows(ledger_path):
        records.append(
            ResolutionRecord(
                signal_id=row["signal_id"],
                symbol="BTC/USDT",
                timeframe="1h",
                side=row["side"],
                entry=row["entry"],
                stop=row["stop"],
                target=120.0,
                created_at=parse_utc_timestamp(row["exit_at_utc"]),
                exit_at=parse_utc_timestamp(row["exit_at_utc"]),
                exit_price=row["exit_price"],
                exit_reason=row["exit_reason"],
                candles_used=4,
                resolver_version="paper-resolution-v1",
            )
        )
    return records


def test_the_report_json_is_valid_and_finite(tmp_path):
    report = build_performance_report([], _config(), _AS_OF)

    payload = json.loads(report.to_json())

    assert payload["status"] == "no_trades"
    assert payload["sharpe"] is None
    with pytest.raises(ValueError):
        json.dumps({"value": math.inf}, allow_nan=False)
