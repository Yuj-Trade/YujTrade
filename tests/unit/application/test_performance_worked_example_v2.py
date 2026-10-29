"""Worked example for cost-model-v2 (`docs/performance-worked-example-v2.md`).

Three trades (target, stop, expired) with a 4 hour holding time, the v2
profile and an entry quote volume of `250000`. Every number below is
recomputed by an independent calculator, not by the implementation.
"""

from datetime import UTC, datetime

import pytest

from application.performance_report import PerformanceConfig, build_performance_report
from domain.costs import CostProfile
from domain.performance import ResolutionRecord

_AS_OF = datetime(2026, 10, 3, 23, 59, 59, tzinfo=UTC)
_ENTRY_VOLUME = 250_000.0

V2_PROFILE = CostProfile(
    version="cost-model-v2",
    maker_fee_rate=0.001,
    taker_fee_rate=0.001,
    entry_liquidity="taker",
    target_exit_liquidity="maker",
    stop_exit_liquidity="taker",
    expiry_exit_liquidity="taker",
    entry_slippage_rate=0.0005,
    market_exit_slippage_rate=0.0005,
    target_exit_slippage_rate=0.0,
    funding_rate_per_period=0.0001,
    funding_period_hours=8.0,
    max_volume_participation=0.05,
)


def _record(
    signal_id: str,
    exit_reason: str,
    exit_price: float,
    exit_at: datetime,
    created_at: datetime,
    volume: float | None = _ENTRY_VOLUME,
) -> ResolutionRecord:
    return ResolutionRecord(
        signal_id=signal_id,
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        entry=100.0,
        stop=90.0,
        target=120.0,
        created_at=created_at,
        exit_at=exit_at,
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="paper-resolution-v1",
        entry_quote_volume=volume,
    )


def _records() -> list[ResolutionRecord]:
    return [
        _record(
            "sig-a",
            "target",
            120.0,
            datetime(2026, 10, 1, 14, tzinfo=UTC),
            datetime(2026, 10, 1, 10, tzinfo=UTC),
        ),
        _record(
            "sig-b",
            "stop",
            90.0,
            datetime(2026, 10, 2, 14, tzinfo=UTC),
            datetime(2026, 10, 2, 10, tzinfo=UTC),
        ),
        _record(
            "sig-c",
            "expired",
            110.0,
            datetime(2026, 10, 3, 14, tzinfo=UTC),
            datetime(2026, 10, 3, 10, tzinfo=UTC),
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
        cost_profile=V2_PROFILE,
    )


def _independent_net_r(
    entry: float, stop: float, exit_price: float, reason: str, hours: float
) -> float:
    risk = abs(entry - stop)
    fee_entry = 0.001
    slip_entry = 0.0005
    fee_exit = 0.001
    slip_exit = 0.0 if reason == "target" else 0.0005
    funding = 0.0001 * (hours / 8.0) * entry
    cost = (fee_entry + slip_entry) * entry + (fee_exit + slip_exit) * exit_price + funding
    return (exit_price - entry - cost) / risk


def _independent_fill_fraction(entry: float, stop: float) -> float:
    reference_risk = 10000.0 * 1.0 / 100.0
    notional = reference_risk * entry / abs(entry - stop)
    return min(1.0, 0.05 * _ENTRY_VOLUME / notional)


_FILL_FRACTION = _independent_fill_fraction(100.0, 90.0)


def test_the_v2_profile_and_coverage_are_pinned():
    report = build_performance_report(_records(), _config(), _AS_OF)

    assert report.report_version == "performance-report-v2"
    assert report.parameters["cost_model_version"] == "cost-model-v2"
    assert report.parameters["maker_fee_rate"] == 0.001
    assert report.parameters["taker_fee_rate"] == 0.001
    assert report.parameters["entry_liquidity"] == "taker"
    assert report.parameters["target_exit_liquidity"] == "maker"
    assert report.parameters["stop_exit_liquidity"] == "taker"
    assert report.parameters["entry_slippage_rate"] == 0.0005
    assert report.parameters["market_exit_slippage_rate"] == 0.0005
    assert report.parameters["target_exit_slippage_rate"] == 0.0
    assert report.parameters["funding_rate_per_period"] == 0.0001
    assert report.parameters["funding_period_hours"] == 8.0
    assert report.parameters["max_volume_participation"] == 0.05
    assert report.coverage == {
        "legacy_resolutions_included": False,
        "legacy_full_fill_records": 0,
        "unfilled_trades": 0,
    }
    assert report.equity_source == "signal_model"


def test_the_v2_expectancy_matches_the_independent_calculator():
    r_target = _FILL_FRACTION * _independent_net_r(100.0, 90.0, 120.0, "target", 4.0)
    r_stop = _FILL_FRACTION * _independent_net_r(100.0, 90.0, 90.0, "stop", 4.0)
    r_expired = _FILL_FRACTION * _independent_net_r(100.0, 90.0, 110.0, "expired", 4.0)

    report = build_performance_report(_records(), _config(), _AS_OF)

    assert report.expectancy_r == pytest.approx((r_target + r_stop + r_expired) / 3.0)
    assert report.win_rate == pytest.approx(2.0 / 3.0)
    assert report.profit_factor == pytest.approx((r_target + r_expired) / abs(r_stop))


def test_the_v2_equity_curve_matches_the_independent_calculator():
    r_target = _FILL_FRACTION * _independent_net_r(100.0, 90.0, 120.0, "target", 4.0)
    r_stop = _FILL_FRACTION * _independent_net_r(100.0, 90.0, 90.0, "stop", 4.0)
    r_expired = _FILL_FRACTION * _independent_net_r(100.0, 90.0, 110.0, "expired", 4.0)
    equity = 10000.0
    for value in (r_target, r_stop, r_expired):
        equity *= 1.0 + value / 100.0

    report = build_performance_report(_records(), _config(), _AS_OF)

    assert report.final_equity == pytest.approx(equity)
    assert report.total_return == pytest.approx(equity / 10000.0 - 1.0)


def test_a_maker_target_pays_no_slippage_while_the_stop_pays_it():
    report = build_performance_report(_records(), _config(), _AS_OF)
    target_report = build_performance_report(_records()[:1], _config(), _AS_OF)

    expected = _FILL_FRACTION * _independent_net_r(100.0, 90.0, 120.0, "target", 4.0)
    assert target_report.expectancy_r == pytest.approx(expected)
    assert report.exit_counts["target"] == 1


def test_the_ratios_match_the_documented_values():
    report = build_performance_report(_records(), _config(min_trades=3), _AS_OF)

    assert report.status == "ok"
    assert report.sharpe == pytest.approx(7.9674171420056314)
    assert report.sortino == pytest.approx(20.490130880473146)


def test_a_zero_volume_book_is_counted_as_unfilled():
    thin = [
        _record(
            "sig-thin",
            "target",
            120.0,
            datetime(2026, 10, 1, 14, tzinfo=UTC),
            datetime(2026, 10, 1, 10, tzinfo=UTC),
            volume=0.0,
        )
    ]

    report = build_performance_report(thin, _config(), _AS_OF)

    assert report.coverage["unfilled_trades"] == 1
    assert report.total_resolved == 0
    assert report.status == "no_trades"


def test_a_dust_fill_stays_positive_but_tiny():
    thin = [
        _record(
            "sig-thin",
            "target",
            120.0,
            datetime(2026, 10, 1, 14, tzinfo=UTC),
            datetime(2026, 10, 1, 10, tzinfo=UTC),
            volume=1.0,
        )
    ]

    report = build_performance_report(thin, _config(), _AS_OF)

    assert report.total_resolved == 1
    assert report.expectancy_r == pytest.approx(
        5e-05 * _independent_net_r(100.0, 90.0, 120.0, "target", 4.0)
    )


def test_a_missing_volume_is_a_legacy_full_fill():
    plain = [
        _record(
            "sig-plain",
            "target",
            120.0,
            datetime(2026, 10, 1, 14, tzinfo=UTC),
            datetime(2026, 10, 1, 10, tzinfo=UTC),
            volume=None,
        )
    ]

    report = build_performance_report(plain, _config(), _AS_OF)

    assert report.coverage["legacy_full_fill_records"] == 1
    assert report.coverage["unfilled_trades"] == 0


def test_a_deeper_book_fills_the_whole_order():
    full = build_performance_report(_records()[:1], _config(), _AS_OF)
    capped = build_performance_report(
        [
            _record(
                "sig-deep",
                "target",
                120.0,
                datetime(2026, 10, 1, 14, tzinfo=UTC),
                datetime(2026, 10, 1, 10, tzinfo=UTC),
                volume=_ENTRY_VOLUME * 10.0,
            )
        ],
        _config(),
        _AS_OF,
    )

    assert _FILL_FRACTION == 1.0
    assert capped.expectancy_r == pytest.approx(
        _independent_net_r(100.0, 90.0, 120.0, "target", 4.0)
    )
    assert full.expectancy_r == capped.expectancy_r
