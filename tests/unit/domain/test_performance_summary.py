"""One source of performance metrics: domains closed-trade summary (P6)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from domain.performance import (
    ClosedTrade,
    PnlTrade,
    fractions_from_pnl,
    summarize_closed_trades,
)

_START = date(2026, 10, 1)
_END = date(2026, 10, 3)


def _at(day: int) -> datetime:
    return datetime(2026, 10, day, 14, tzinfo=UTC)


def _config(**overrides):
    base = {
        "initial_equity": 10000.0,
        "start": _START,
        "end": _END,
        "periods_per_year": 365.0,
        "rf_annual": 0.0,
        "min_trades_for_ratios": 3,
    }
    base.update(overrides)
    return base


def test_an_empty_sample_has_no_ratios():
    summary = summarize_closed_trades([], **_config())

    assert summary.status == "no_trades"
    assert summary.total_closed == 0
    assert summary.sharpe is None
    assert summary.sortino is None
    assert summary.final_equity == 10000.0
    assert summary.total_return == 0.0
    assert summary.max_drawdown == 0.0


def test_one_trade_is_an_insufficient_sample():
    trade = ClosedTrade(_at(1), "sig-1", 0.02)
    summary = summarize_closed_trades([trade], **_config())

    assert summary.status == "insufficient_sample"
    assert summary.total_closed == 1
    assert summary.final_equity == pytest.approx(10200.0)
    assert summary.sharpe is None


def test_the_formulas_match_the_worked_example():
    trades = [
        ClosedTrade(_at(1), "sig-a", 0.01967),
        ClosedTrade(_at(2), "sig-b", -0.010285),
        ClosedTrade(_at(3), "sig-c", 0.009685),
    ]
    summary = summarize_closed_trades(trades, **_config())

    assert summary.status == "ok"
    assert summary.final_equity == pytest.approx(10189.566284418743)
    assert summary.sharpe == pytest.approx(7.962315986966122)
    assert summary.sortino == pytest.approx(20.451831307422246)
    assert summary.max_drawdown == pytest.approx(0.010284999999999973)


def test_a_zero_spread_yields_no_sharpe():
    trades = [
        ClosedTrade(_at(1), "sig-a", 0.01),
        ClosedTrade(_at(2), "sig-b", 0.01),
        ClosedTrade(_at(3), "sig-c", 0.01),
    ]
    summary = summarize_closed_trades(trades, **_config())

    assert summary.status == "ok"
    assert summary.sharpe is None
    assert summary.sortino is None


def test_fractions_from_pnl_uses_a_sequential_equity():
    trades = [
        PnlTrade(_at(2), "sig-b", -100.0),
        PnlTrade(_at(1), "sig-a", 100.0),
    ]
    closed = fractions_from_pnl(trades, 1000.0)

    assert [trade.signal_id for trade in closed] == ["sig-a", "sig-b"]
    assert closed[0].return_fraction == pytest.approx(0.1)
    assert closed[1].return_fraction == pytest.approx(-100.0 / 1100.0)


def test_fractions_from_pnl_orders_by_exit_then_signal_id():
    same_day = _at(1)
    trades = [
        PnlTrade(same_day, "sig-b", 10.0),
        PnlTrade(same_day, "sig-a", 10.0),
    ]

    closed = fractions_from_pnl(trades, 1000.0)

    assert [trade.signal_id for trade in closed] == ["sig-a", "sig-b"]


def test_fractions_from_pnl_rejects_a_wipe_out():
    with pytest.raises(ValueError):
        fractions_from_pnl([PnlTrade(_at(1), "sig-1", -1000.0)], 1000.0)


def test_a_naive_exit_is_rejected():
    with pytest.raises(ValueError):
        ClosedTrade(datetime(2026, 10, 1, 14), "sig-1", 0.01)


def test_a_fraction_at_or_below_minus_one_is_rejected():
    with pytest.raises(ValueError):
        ClosedTrade(_at(1), "sig-1", -1.0)


def test_a_non_finite_fraction_is_rejected():
    with pytest.raises(ValueError):
        ClosedTrade(_at(1), "sig-1", float("nan"))


def test_a_negative_minimum_is_rejected():
    with pytest.raises(ValueError):
        summarize_closed_trades([], **_config(min_trades_for_ratios=-1))


def test_the_summary_matches_the_report_formula_for_the_same_fractions():
    trades = [
        ClosedTrade(_at(1), "sig-a", 0.01),
        ClosedTrade(_at(2), "sig-b", -0.02),
        ClosedTrade(_at(3), "sig-c", 0.03),
    ]
    summary = summarize_closed_trades(trades, **_config(min_trades_for_ratios=2))

    assert summary.status == "ok"
    assert summary.sharpe is not None
    assert summary.sortino is not None
    assert summary.final_equity == pytest.approx(10000.0 * 1.01 * 0.98 * 1.03)


def test_the_window_is_respected():
    trades = [ClosedTrade(_at(day), f"sig-{day}", 0.01) for day in (1, 2, 3)]
    summary = summarize_closed_trades(
        trades, **_config(start=_START, end=_START + timedelta(days=10))
    )

    assert summary.total_closed == 3
    assert summary.final_equity == pytest.approx(10000.0 * 1.01**3)
