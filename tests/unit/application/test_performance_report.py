import json
import math
from datetime import UTC, datetime

import pytest

from application.performance_report import (
    PerformanceConfig,
    build_performance_report,
)
from domain.performance import ResolutionRecord

_AS_OF = datetime(2026, 10, 20, 12, tzinfo=UTC)


def _config(**overrides) -> PerformanceConfig:
    base = {
        "initial_cash": 10000.0,
        "risk_per_trade_pct": 1.0,
        "fee_rate": 0.0,
        "slippage_rate": 0.0,
        "rf_annual": 0.0,
        "periods_per_year": 365.0,
        "min_trades_for_ratios": 3,
    }
    base.update(overrides)
    return PerformanceConfig(**base)


def _record(
    signal_id: str = "sig-1",
    exit_reason: str = "target",
    exit_price: float | None = 120.0,
    entry: float = 100.0,
    stop: float = 90.0,
    exit_at: datetime | None = datetime(2026, 10, 1, 14, tzinfo=UTC),
    created_at: datetime = datetime(2026, 10, 1, 10, tzinfo=UTC),
) -> ResolutionRecord:
    return ResolutionRecord(
        signal_id=signal_id,
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        entry=entry,
        stop=stop,
        target=120.0,
        created_at=created_at,
        exit_at=exit_at,
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="paper-resolution-v1",
    )


def test_an_empty_record_list_reports_no_trades():
    report = build_performance_report([], _config(), _AS_OF)

    assert report.status == "no_trades"
    assert report.total_resolved == 0
    assert report.win_rate is None
    assert report.profit_factor is None
    assert report.expectancy_r is None
    assert report.sharpe is None
    assert report.sortino is None
    assert report.initial_equity == 10000.0
    assert report.final_equity == 10000.0
    assert report.total_return == 0.0
    assert report.exit_counts == {"stop": 0, "target": 0, "expired": 0, "no_data": 0}


def test_only_no_data_records_report_no_trades_and_count_the_no_data():
    records = [
        _record(
            signal_id="sig-1",
            exit_reason="no_data",
            exit_price=None,
            exit_at=None,
            created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        )
    ]

    report = build_performance_report(records, _config(), _AS_OF)

    assert report.status == "no_trades"
    assert report.total_resolved == 0
    assert report.exit_counts["no_data"] == 1
    assert report.final_equity == 10000.0


def test_a_single_trade_reports_an_insufficient_sample():
    report = build_performance_report([_record()], _config(), _AS_OF)

    assert report.status == "insufficient_sample"
    assert report.total_resolved == 1
    assert report.win_rate == pytest.approx(1.0)
    assert report.expectancy_r == pytest.approx(2.0)
    assert report.sharpe is None
    assert report.sortino is None
    assert report.final_equity == pytest.approx(10000.0 * 1.02)


def test_enough_trades_report_the_ratios():
    records = [
        _record(signal_id="sig-1", exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC)),
        _record(
            signal_id="sig-2",
            exit_reason="stop",
            exit_price=90.0,
            exit_at=datetime(2026, 10, 2, 14, tzinfo=UTC),
            created_at=datetime(2026, 10, 2, 10, tzinfo=UTC),
        ),
        _record(
            signal_id="sig-3",
            exit_reason="expired",
            exit_price=110.0,
            exit_at=datetime(2026, 10, 3, 14, tzinfo=UTC),
            created_at=datetime(2026, 10, 3, 10, tzinfo=UTC),
        ),
    ]

    report = build_performance_report(records, _config(), _AS_OF)

    assert report.status == "ok"
    assert report.total_resolved == 3
    assert report.win_rate == pytest.approx(2.0 / 3.0)
    assert report.expectancy_r == pytest.approx((2.0 - 1.0 + 1.0) / 3.0)
    assert report.profit_factor == pytest.approx(3.0 / 1.0)
    assert report.sharpe is not None
    assert report.sortino is not None
    assert report.exit_counts == {"stop": 1, "target": 1, "expired": 1, "no_data": 0}


def test_the_report_does_not_depend_on_the_input_order():
    records = [
        _record(signal_id="sig-1", exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC)),
        _record(
            signal_id="sig-2",
            exit_reason="stop",
            exit_price=90.0,
            exit_at=datetime(2026, 10, 2, 14, tzinfo=UTC),
            created_at=datetime(2026, 10, 2, 10, tzinfo=UTC),
        ),
        _record(
            signal_id="sig-3",
            exit_reason="expired",
            exit_price=110.0,
            exit_at=datetime(2026, 10, 3, 14, tzinfo=UTC),
            created_at=datetime(2026, 10, 3, 10, tzinfo=UTC),
        ),
    ]

    first = build_performance_report(records, _config(), _AS_OF)
    second = build_performance_report(list(reversed(records)), _config(), _AS_OF)

    assert first.data_hash == second.data_hash
    assert first.final_equity == second.final_equity
    assert first.sharpe == second.sharpe
    assert first.max_drawdown == second.max_drawdown


def test_a_changed_record_changes_the_data_hash():
    baseline = build_performance_report([_record()], _config(), _AS_OF)
    changed = build_performance_report([_record(exit_price=121.0)], _config(), _AS_OF)

    assert baseline.data_hash != changed.data_hash


def test_a_changed_parameter_changes_the_config_hash():
    baseline = build_performance_report([_record()], _config(), _AS_OF)
    changed = build_performance_report([_record()], _config(risk_per_trade_pct=2.0), _AS_OF)

    assert baseline.config_hash != changed.config_hash
    assert baseline.data_hash == changed.data_hash


def test_the_json_output_contains_no_nan_and_no_infinity():
    records = [
        _record(signal_id="sig-1", exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC)),
        _record(
            signal_id="sig-2",
            exit_reason="stop",
            exit_price=90.0,
            exit_at=datetime(2026, 10, 2, 14, tzinfo=UTC),
            created_at=datetime(2026, 10, 2, 10, tzinfo=UTC),
        ),
    ]

    report = build_performance_report(records, _config(), _AS_OF)
    payload = report.to_json()

    assert "NaN" not in payload
    assert "Infinity" not in payload
    assert math.isnan(json.loads(payload)["total_return"]) is False


def test_the_report_carries_the_version_the_mode_and_the_window():
    report = build_performance_report([_record()], _config(), _AS_OF)

    assert report.report_version == "performance-report-v1"
    assert report.mode == "paper"
    assert report.as_of == "2026-10-20T12:00:00.000000+00:00"
    assert report.period_start == "2026-10-01"
    assert report.period_end == "2026-10-20"


def test_the_report_carries_the_effective_parameters():
    report = build_performance_report([_record()], _config(), _AS_OF)

    assert report.parameters["risk_per_trade_pct"] == 1.0
    assert report.parameters["fee_rate"] == 0.0
    assert report.parameters["slippage_rate"] == 0.0
    assert report.parameters["rf_annual"] == 0.0
    assert report.parameters["periods_per_year"] == 365.0
    assert report.parameters["min_trades_for_ratios"] == 3
    assert report.parameters["initial_cash"] == 10000.0


def test_the_costs_are_charged_on_both_legs():
    report = build_performance_report(
        [_record()], _config(fee_rate=0.001, slippage_rate=0.0005), _AS_OF
    )

    assert report.expectancy_r == pytest.approx(1.967)


def test_the_maximum_drawdown_reports_the_peak_and_the_trough():
    records = [
        _record(signal_id="sig-1", exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC)),
        _record(
            signal_id="sig-2",
            exit_reason="stop",
            exit_price=90.0,
            exit_at=datetime(2026, 10, 2, 14, tzinfo=UTC),
            created_at=datetime(2026, 10, 2, 10, tzinfo=UTC),
        ),
        _record(
            signal_id="sig-3",
            exit_reason="target",
            exit_price=130.0,
            exit_at=datetime(2026, 10, 3, 14, tzinfo=UTC),
            created_at=datetime(2026, 10, 3, 10, tzinfo=UTC),
        ),
    ]

    report = build_performance_report(records, _config(), _AS_OF)

    assert report.max_drawdown.depth > 0.0
    assert report.max_drawdown.peak_index >= 0
    assert report.max_drawdown.trough_index > report.max_drawdown.peak_index
    assert report.max_drawdown.duration_trades == (
        report.max_drawdown.trough_index - report.max_drawdown.peak_index
    )
    assert report.max_drawdown.peak_time is not None
    assert report.max_drawdown.trough_time is not None


def test_a_naive_as_of_is_rejected():
    with pytest.raises(ValueError):
        build_performance_report([_record()], _config(), datetime(2026, 10, 20, 12))


def test_a_record_after_the_as_of_is_excluded():
    records = [
        _record(signal_id="sig-1", exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC)),
        _record(
            signal_id="sig-2",
            exit_at=datetime(2026, 11, 1, 14, tzinfo=UTC),
            created_at=datetime(2026, 11, 1, 10, tzinfo=UTC),
        ),
    ]

    report = build_performance_report(records, _config(), _AS_OF)

    assert report.total_resolved == 1
    assert report.exit_counts["target"] == 1
