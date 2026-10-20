"""The numbers of `docs/performance-worked-example.md` are pinned here.

The document shows three trades (target, stop, expired) with the full
step-by-step arithmetic. If an implementation change moves any of these
numbers, this test fails and the document has to be updated with it.
"""

from datetime import UTC, datetime

import pytest

from application.performance_report import PerformanceConfig, build_performance_report
from domain.performance import ResolutionRecord

_AS_OF = datetime(2026, 10, 3, 23, 59, 59, tzinfo=UTC)


def _records() -> list[ResolutionRecord]:
    return [
        ResolutionRecord(
            signal_id="sig-a",
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
        ),
        ResolutionRecord(
            signal_id="sig-b",
            symbol="BTC/USDT",
            timeframe="1h",
            side="buy",
            entry=100.0,
            stop=90.0,
            target=120.0,
            created_at=datetime(2026, 10, 2, 10, tzinfo=UTC),
            exit_at=datetime(2026, 10, 2, 14, tzinfo=UTC),
            exit_price=90.0,
            exit_reason="stop",
            candles_used=4,
            resolver_version="paper-resolution-v1",
        ),
        ResolutionRecord(
            signal_id="sig-c",
            symbol="ETH/USDT",
            timeframe="1h",
            side="buy",
            entry=100.0,
            stop=90.0,
            target=120.0,
            created_at=datetime(2026, 10, 3, 10, tzinfo=UTC),
            exit_at=datetime(2026, 10, 3, 14, tzinfo=UTC),
            exit_price=110.0,
            exit_reason="expired",
            candles_used=12,
            resolver_version="paper-resolution-v1",
        ),
    ]


def _config(min_trades: int = 30) -> PerformanceConfig:
    return PerformanceConfig(
        initial_cash=10000.0,
        risk_per_trade_pct=1.0,
        fee_rate=0.001,
        slippage_rate=0.0005,
        rf_annual=0.0,
        periods_per_year=365.0,
        min_trades_for_ratios=min_trades,
    )


def test_the_worked_example_matches_the_documented_report():
    report = build_performance_report(_records(), _config(), _AS_OF)

    assert report.report_version == "performance-report-v1"
    assert report.mode == "paper"
    assert report.as_of == "2026-10-03T23:59:59.000000+00:00"
    assert report.period_start == "2026-10-01"
    assert report.period_end == "2026-10-03"
    assert report.status == "insufficient_sample"
    assert report.total_resolved == 3
    assert report.exit_counts == {"stop": 1, "target": 1, "expired": 1, "no_data": 0}
    assert report.win_rate == pytest.approx(0.6666666666666666)
    assert report.profit_factor == pytest.approx(2.8541565386485175)
    assert report.expectancy_r == pytest.approx(0.6356666666666667)
    assert report.initial_equity == 10000.0
    assert report.final_equity == pytest.approx(10189.566284418743)
    assert report.total_return == pytest.approx(0.01895662844187429)
    assert report.sharpe is None
    assert report.sortino is None
    assert report.data_hash == ("2a803a8d09eae9858d88e9fa9b82b2b5043c9cf79b3854c7939151308ec17dd6")
    assert report.config_hash == (
        "a6ff27074d338465c91eee54b7501ef68c1c36e378b9a45f3a5e57b77c4c0c17"
    )


def test_the_worked_example_matches_the_documented_drawdown():
    report = build_performance_report(_records(), _config(), _AS_OF)
    drawdown = report.max_drawdown

    assert drawdown.depth == pytest.approx(0.010284999999999973)
    assert drawdown.peak_index == 1
    assert drawdown.trough_index == 2
    assert drawdown.duration_trades == 1
    assert drawdown.peak_time == "2026-10-01T14:00:00.000000+00:00"
    assert drawdown.trough_time == "2026-10-02T14:00:00.000000+00:00"


def test_the_worked_example_ratio_variant_matches_the_documented_ratios():
    report = build_performance_report(_records(), _config(min_trades=3), _AS_OF)

    assert report.status == "ok"
    assert report.sharpe == pytest.approx(7.962315986966122)
    assert report.sortino == pytest.approx(20.451831307422246)
    assert report.config_hash == (
        "3b52ca2c086a3f140a15c8da7965b3ae4207b0064e96ad104da63c7f2a5428e7"
    )
    assert report.data_hash == ("2a803a8d09eae9858d88e9fa9b82b2b5043c9cf79b3854c7939151308ec17dd6")
