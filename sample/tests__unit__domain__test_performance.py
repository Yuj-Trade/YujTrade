import math
from datetime import UTC, date, datetime

import pytest

from domain.performance import (
    ResolutionRecord,
    daily_returns,
    equity_curve,
    expectancy,
    fixed_fraction_return,
    max_drawdown,
    net_r_multiple,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)


def _record(
    side: str = "buy",
    entry: float = 100.0,
    stop: float = 90.0,
    exit_price: float | None = 120.0,
    exit_reason: str = "target",
) -> ResolutionRecord:
    return ResolutionRecord(
        signal_id="sig-1",
        symbol="BTC/USDT",
        timeframe="1h",
        side=side,
        entry=entry,
        stop=stop,
        target=120.0,
        created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        resolved_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="v1",
    )


def test_buy_target_is_plus_two_r_without_costs():
    assert net_r_multiple(_record(), 0.0, 0.0) == pytest.approx(2.0)


def test_buy_target_with_costs_subtracts_round_trip_cost_in_r():
    expected = 2.0 - (0.001 + 0.0005) * (100.0 + 120.0) / 10.0
    assert net_r_multiple(_record(), 0.001, 0.0005) == pytest.approx(expected)
    assert expected == pytest.approx(1.967)


def test_sell_stop_is_minus_one_r_without_costs():
    record = _record(side="sell", entry=100.0, stop=110.0, exit_price=110.0, exit_reason="stop")
    assert net_r_multiple(record, 0.0, 0.0) == pytest.approx(-1.0)


def test_sell_target_is_plus_two_r_without_costs():
    record = _record(side="sell", entry=100.0, stop=110.0, exit_price=80.0)
    assert net_r_multiple(record, 0.0, 0.0) == pytest.approx(2.0)


def test_net_r_rejects_no_data_resolution():
    record = _record(exit_price=None, exit_reason="no_data")
    with pytest.raises(ValueError):
        net_r_multiple(record, 0.0, 0.0)


def test_net_r_rejects_negative_cost_rates():
    with pytest.raises(ValueError):
        net_r_multiple(_record(), -0.001, 0.0)


def test_fixed_fraction_return_scales_r_by_risk_percentage():
    assert fixed_fraction_return(2.0, 1.0) == pytest.approx(0.02)
    assert fixed_fraction_return(-1.0, 0.5) == pytest.approx(-0.005)


def test_fixed_fraction_return_rejects_invalid_risk():
    with pytest.raises(ValueError):
        fixed_fraction_return(1.0, 0.0)
    with pytest.raises(ValueError):
        fixed_fraction_return(1.0, 101.0)


def test_equity_curve_compounds_fractions():
    assert equity_curve(1000.0, [0.1, -0.05]) == pytest.approx([1000.0, 1100.0, 1045.0])


def test_equity_curve_of_no_trades_is_initial_only():
    assert equity_curve(500.0, []) == [500.0]


def test_equity_curve_rejects_wipeout_fraction():
    with pytest.raises(ValueError):
        equity_curve(1000.0, [-1.0])


def test_max_drawdown_finds_deepest_trough_and_its_peak():
    drawdown = max_drawdown([100.0, 120.0, 90.0, 110.0, 80.0])
    assert drawdown.depth == pytest.approx(1.0 / 3.0)
    assert drawdown.peak_index == 1
    assert drawdown.trough_index == 4
    assert drawdown.duration == 3


def test_max_drawdown_of_monotonic_curve_is_zero():
    drawdown = max_drawdown([1.0, 2.0, 3.0])
    assert drawdown.depth == 0.0
    assert drawdown.duration == 0


def test_max_drawdown_rejects_empty_series():
    with pytest.raises(ValueError):
        max_drawdown([])


def test_daily_returns_groups_by_day_and_fills_idle_days_with_zero():
    events = [(date(2026, 10, 1), 0.1), (date(2026, 10, 1), 0.1)]
    returns = daily_returns(events, date(2026, 10, 1), date(2026, 10, 3))
    assert returns == pytest.approx([0.21, 0.0, 0.0])


def test_daily_returns_rejects_events_outside_window():
    with pytest.raises(ValueError):
        daily_returns([(date(2026, 9, 30), 0.1)], date(2026, 10, 1), date(2026, 10, 3))


def test_sharpe_matches_hand_computed_value():
    returns = [0.01, -0.01, 0.02, 0.0]
    expected = (0.005 / math.sqrt(0.0005 / 3.0)) * math.sqrt(365.0)
    assert sharpe_ratio(returns, 0.0, 365.0) == pytest.approx(expected)


def test_sharpe_subtracts_risk_free_rate_per_period():
    returns = [0.01, -0.01, 0.02, 0.0]
    shifted = [value + 0.001 for value in returns]
    assert sharpe_ratio(shifted, 0.001, 365.0) == pytest.approx(sharpe_ratio(returns, 0.0, 365.0))


def test_sharpe_is_none_for_single_observation():
    assert sharpe_ratio([0.01], 0.0, 365.0) is None


def test_sharpe_is_none_for_constant_returns():
    assert sharpe_ratio([0.01, 0.01, 0.01], 0.0, 365.0) is None


def test_sharpe_rejects_nan_input():
    with pytest.raises(ValueError):
        sharpe_ratio([0.01, math.nan], 0.0, 365.0)


def test_sortino_matches_hand_computed_value():
    returns = [0.01, -0.01, 0.02, 0.0]
    expected = (0.005 / 0.005) * math.sqrt(365.0)
    assert sortino_ratio(returns, 0.0, 365.0) == pytest.approx(expected)


def test_sortino_uses_all_observations_in_downside_denominator():
    returns = [0.02, 0.02, -0.01, 0.02]
    mean = sum(returns) / 4.0
    downside = math.sqrt((0.01**2) / 4.0)
    expected = (mean / downside) * math.sqrt(365.0)
    assert sortino_ratio(returns, 0.0, 365.0) == pytest.approx(expected)


def test_sortino_is_none_without_any_downside():
    assert sortino_ratio([0.01, 0.02], 0.0, 365.0) is None


def test_sortino_is_none_for_single_observation():
    assert sortino_ratio([-0.01], 0.0, 365.0) is None


def test_win_rate_counts_strictly_positive_r():
    assert win_rate([2.0, -1.0, 0.0, 1.5]) == pytest.approx(0.5)


def test_win_rate_is_none_for_empty_input():
    assert win_rate([]) is None


def test_profit_factor_is_gains_over_losses():
    assert profit_factor([2.0, -1.0, 1.0, -0.5]) == pytest.approx(3.0 / 1.5)


def test_profit_factor_is_none_without_losses():
    assert profit_factor([1.0, 2.0]) is None


def test_expectancy_is_mean_r():
    assert expectancy([2.0, -1.0, 0.0]) == pytest.approx(1.0 / 3.0)


def test_expectancy_is_none_for_empty_input():
    assert expectancy([]) is None


def test_resolution_record_rejects_naive_timestamps():
    with pytest.raises(ValueError):
        ResolutionRecord(
            signal_id="sig-1",
            symbol="BTC/USDT",
            timeframe="1h",
            side="buy",
            entry=100.0,
            stop=90.0,
            target=120.0,
            created_at=datetime(2026, 10, 1, 10),
            resolved_at=datetime(2026, 10, 1, 14),
            exit_price=120.0,
            exit_reason="target",
            candles_used=4,
            resolver_version="v1",
        )


def test_resolution_record_rejects_stop_on_wrong_side():
    with pytest.raises(ValueError):
        _record(side="buy", entry=100.0, stop=105.0)


def test_resolution_record_rejects_price_for_no_data():
    with pytest.raises(ValueError):
        _record(exit_price=100.0, exit_reason="no_data")


def test_resolution_record_requires_price_for_resolved_exit():
    with pytest.raises(ValueError):
        _record(exit_price=None, exit_reason="expired")


def test_resolution_record_rejects_unknown_exit_reason():
    with pytest.raises(ValueError):
        _record(exit_reason="timeout")


def test_resolution_record_rejects_unknown_side():
    with pytest.raises(ValueError):
        _record(side="long")
