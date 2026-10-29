"""The report and the paper portfolio agree on the same outcomes (P6)."""

from datetime import UTC, date, datetime

import pytest

from application.performance_report import (
    PerformanceConfig,
    build_performance_report,
    build_portfolio_summary,
)
from domain.costs import legacy_report_profile
from domain.performance import ClosedTrade, ResolutionRecord

_AS_OF = datetime(2026, 10, 3, 23, 59, 59, tzinfo=UTC)
_RISK_PCT = 1.0


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
            entry_quote_volume=1e9,
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
            entry_quote_volume=1e9,
        ),
        ResolutionRecord(
            signal_id="sig-c",
            symbol="BTC/USDT",
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
            entry_quote_volume=1e9,
        ),
    ]


def _config() -> PerformanceConfig:
    return PerformanceConfig(
        initial_cash=10000.0,
        risk_per_trade_pct=_RISK_PCT,
        fee_rate=0.001,
        slippage_rate=0.0005,
        rf_annual=0.0,
        periods_per_year=365.0,
        min_trades_for_ratios=3,
        cost_profile=legacy_report_profile(0.001, 0.0005),
    )


def _closed_from_report() -> list[ClosedTrade]:
    report = build_performance_report(_records(), _config(), _AS_OF)
    fraction_per_r = _RISK_PCT / 100.0
    return [
        ClosedTrade(
            record.exit_at,
            record.signal_id,
            r_value * fraction_per_r,
        )
        for record, r_value in zip(_records(), _r_values(report), strict=True)
    ]


def _r_values(report) -> list[float]:
    from domain.costs import legacy_report_profile
    from domain.performance import net_r_for_profile

    profile = legacy_report_profile(0.001, 0.0005)
    values = []
    for record in _records():
        holding = (record.exit_at - record.created_at).total_seconds() / 3600.0
        values.append(net_r_for_profile(record, profile, 1.0, holding))
    return values


def test_the_report_and_the_portfolio_summary_agree():
    report = build_performance_report(_records(), _config(), _AS_OF)
    summary = build_portfolio_summary(
        _closed_from_report(),
        10000.0,
        start=date(2026, 10, 1),
        end=date(2026, 10, 3),
        periods_per_year=365.0,
        rf_annual=0.0,
        min_trades_for_ratios=3,
    )

    assert summary["equity_source"] == "paper_portfolio"
    assert summary["sharpe"] == pytest.approx(report.sharpe, rel=1e-9)
    assert summary["sortino"] == pytest.approx(report.sortino, rel=1e-9)
    assert summary["max_drawdown"] == pytest.approx(report.max_drawdown.depth, rel=1e-9)
    assert summary["final_equity"] == pytest.approx(report.final_equity, rel=1e-9)
    assert summary["total_return"] == pytest.approx(report.total_return, rel=1e-9)


def test_the_two_views_are_labelled_differently():
    report = build_performance_report(_records(), _config(), _AS_OF)
    summary = build_portfolio_summary(
        _closed_from_report(),
        10000.0,
        start=date(2026, 10, 1),
        end=date(2026, 10, 3),
        periods_per_year=365.0,
        rf_annual=0.0,
        min_trades_for_ratios=3,
    )

    assert report.equity_source == "signal_model"
    assert summary["equity_source"] == "paper_portfolio"


def test_an_empty_portfolio_summary_is_no_trades():
    summary = build_portfolio_summary(
        [],
        10000.0,
        start=date(2026, 10, 1),
        end=date(2026, 10, 3),
        periods_per_year=365.0,
        rf_annual=0.0,
        min_trades_for_ratios=3,
    )

    assert summary["status"] == "no_trades"
    assert summary["sharpe"] is None
    assert summary["final_equity"] == 10000.0
