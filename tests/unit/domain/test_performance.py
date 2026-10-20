import math
from datetime import UTC, date, datetime

import pytest

from domain.performance import (
    ResolutionRecord,
    daily_returns,
    equity_curve,
    expectancy,
    fixed_fraction_return,
    format_utc_timestamp,
    max_drawdown,
    net_r_multiple,
    parse_utc_timestamp,
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
    exit_at: datetime | None = datetime(2026, 10, 1, 14, tzinfo=UTC),
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
        exit_at=exit_at,
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="paper-resolution-v1",
    )


def test_a_valid_record_is_accepted():
    record = _record()

    assert record.utc_created_at() == datetime(2026, 10, 1, 10, tzinfo=UTC)
    assert record.utc_exit_at() == datetime(2026, 10, 1, 14, tzinfo=UTC)


def test_a_no_data_record_has_no_exit_time():
    record = _record(exit_price=None, exit_reason="no_data", exit_at=None)

    assert record.utc_exit_at() is None


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
            exit_at=datetime(2026, 10, 1, 14),
            exit_price=120.0,
            exit_reason="target",
            candles_used=4,
            resolver_version="v1",
        )


def test_resolution_record_rejects_stop_on_wrong_side():
    with pytest.raises(ValueError):
        _record(side="buy", entry=100.0, stop=105.0)
    with pytest.raises(ValueError):
        _record(side="sell", entry=100.0, stop=95.0)


def test_resolution_record_rejects_price_for_no_data():
    with pytest.raises(ValueError):
        _record(exit_price=100.0, exit_reason="no_data", exit_at=None)


def test_resolution_record_rejects_exit_time_for_no_data():
    with pytest.raises(ValueError):
        _record(exit_price=None, exit_reason="no_data")


def test_resolution_record_requires_price_for_resolved_exit():
    with pytest.raises(ValueError):
        _record(exit_price=None, exit_reason="expired")


def test_resolution_record_requires_exit_time_for_resolved_exit():
    with pytest.raises(ValueError):
        _record(exit_at=None)


def test_resolution_record_rejects_an_exit_before_the_creation():
    with pytest.raises(ValueError):
        _record(exit_at=datetime(2026, 10, 1, 9, tzinfo=UTC))


def test_resolution_record_rejects_unknown_exit_reason():
    with pytest.raises(ValueError):
        _record(exit_reason="timeout")


def test_resolution_record_rejects_unknown_side():
    with pytest.raises(ValueError):
        _record(side="long")


def test_resolution_record_rejects_a_non_positive_entry():
    with pytest.raises(ValueError):
        _record(entry=0.0)


def test_resolution_record_rejects_a_negative_candle_count():
    with pytest.raises(ValueError):
        ResolutionRecord(
            signal_id="sig-1",
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
            candles_used=-1,
            resolver_version="v1",
        )


def test_resolution_record_rejects_an_empty_signal_id():
    with pytest.raises(ValueError):
        ResolutionRecord(
            signal_id="",
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
            resolver_version="v1",
        )


def test_timestamps_use_the_fixed_utc_format():
    formatted = format_utc_timestamp(datetime(2026, 10, 1, 14, tzinfo=UTC))

    assert formatted == "2026-10-01T14:00:00.000000+00:00"


def test_timestamps_round_trip_through_the_fixed_format():
    original = datetime(2026, 10, 1, 14, 30, 15, 123456, tzinfo=UTC)

    assert parse_utc_timestamp(format_utc_timestamp(original)) == original


def test_lexicographic_timestamp_order_matches_chronological_order():
    earlier = format_utc_timestamp(datetime(2026, 10, 1, 14, tzinfo=UTC))
    later = format_utc_timestamp(datetime(2026, 10, 1, 15, tzinfo=UTC))

    assert earlier < later


def test_buy_target_is_plus_two_r_without_costs():
    assert net_r_multiple(_record(), 0.0, 0.0) == pytest.approx(2.0)


def test_buy_target_with_costs_subtracts_the_round_trip_cost_in_r():
    expected = 2.0 - (0.001 + 0.0005) * (100.0 + 120.0) / 10.0

    assert net_r_multiple(_record(), 0.001, 0.0005) == pytest.approx(expected)
    assert expected == pytest.approx(1.967)


def test_sell_stop_is_minus_one_r_without_costs():
    record = _record(side="sell", entry=100.0, stop=110.0, exit_price=110.0, exit_reason="stop")

    assert net_r_multiple(record, 0.0, 0.0) == pytest.approx(-1.0)


def test_sell_target_is_plus_two_r_without_costs():
    record = _record(side="sell", entry=100.0, stop=110.0, exit_price=80.0)

    assert net_r_multiple(record, 0.0, 0.0) == pytest.approx(2.0)


def test_net_r_rejects_a_no_data_resolution():
    with pytest.raises(ValueError):
        net_r_multiple(_record(exit_price=None, exit_reason="no_data", exit_at=None), 0.0, 0.0)


def test_net_r_rejects_negative_cost_rates():
    with pytest.raises(ValueError):
        net_r_multiple(_record(), -0.001, 0.0)


def test_fixed_fraction_return_scales_r_by_the_risk_percentage():
    assert fixed_fraction_return(2.0, 1.0) == pytest.approx(0.02)
    assert fixed_fraction_return(-1.0, 0.5) == pytest.approx(-0.005)


def test_fixed_fraction_return_rejects_an_invalid_risk():
    with pytest.raises(ValueError):
        fixed_fraction_return(1.0, 0.0)
    with pytest.raises(ValueError):
        fixed_fraction_return(1.0, 101.0)


def test_equity_curve_compounds_the_fractions():
    assert equity_curve(1000.0, [0.1, -0.05]) == pytest.approx([1000.0, 1100.0, 1045.0])


def test_equity_curve_of_no_trades_is_the_initial_equity_only():
    assert equity_curve(500.0, []) == [500.0]


def test_equity_curve_rejects_a_wipeout_fraction():
    with pytest.raises(ValueError):
        equity_curve(1000.0, [-1.0])


def test_equity_curve_rejects_a_non_positive_initial_equity():
    with pytest.raises(ValueError):
        equity_curve(0.0, [0.1])


def test_max_drawdown_finds_the_deepest_trough_and_its_peak():
    drawdown = max_drawdown([100.0, 120.0, 90.0, 110.0, 80.0])

    assert drawdown.depth == pytest.approx(1.0 / 3.0)
    assert drawdown.peak_index == 1
    assert drawdown.trough_index == 4
    assert drawdown.duration == 3


def test_max_drawdown_reports_the_peak_and_the_trough_time():
    times = [
        datetime(2026, 10, 1, 10, tzinfo=UTC),
        datetime(2026, 10, 1, 11, tzinfo=UTC),
        datetime(2026, 10, 1, 12, tzinfo=UTC),
        datetime(2026, 10, 1, 13, tzinfo=UTC),
        datetime(2026, 10, 1, 14, tzinfo=UTC),
    ]

    drawdown = max_drawdown([100.0, 120.0, 90.0, 110.0, 80.0], times)

    assert drawdown.peak_time == datetime(2026, 10, 1, 11, tzinfo=UTC)
    assert drawdown.trough_time == datetime(2026, 10, 1, 14, tzinfo=UTC)


def test_max_drawdown_of_a_monotonic_curve_is_zero():
    drawdown = max_drawdown([1.0, 2.0, 3.0])

    assert drawdown.depth == 0.0
    assert drawdown.duration == 0


def test_max_drawdown_rejects_an_empty_series():
    with pytest.raises(ValueError):
        max_drawdown([])


def test_max_drawdown_rejects_mismatched_times():
    with pytest.raises(ValueError):
        max_drawdown([1.0, 2.0], [datetime(2026, 10, 1, tzinfo=UTC)])


def test_daily_returns_groups_by_day_and_fills_the_idle_days_with_zero():
    events = [(date(2026, 10, 1), 0.1), (date(2026, 10, 1), 0.1)]

    returns = daily_returns(events, date(2026, 10, 1), date(2026, 10, 3))

    assert returns == pytest.approx([0.21, 0.0, 0.0])


def test_daily_returns_rejects_events_outside_the_window():
    with pytest.raises(ValueError):
        daily_returns([(date(2026, 9, 30), 0.1)], date(2026, 10, 1), date(2026, 10, 3))


def test_daily_returns_rejects_a_reversed_window():
    with pytest.raises(ValueError):
        daily_returns([], date(2026, 10, 3), date(2026, 10, 1))


def test_sharpe_matches_the_hand_computed_value():
    returns = [0.01, -0.01, 0.02, 0.0]
    expected = (0.005 / math.sqrt(0.0005 / 3.0)) * math.sqrt(365.0)

    assert sharpe_ratio(returns, 0.0, 365.0) == pytest.approx(expected)


def test_sharpe_subtracts_the_risk_free_rate_per_period():
    returns = [0.01, -0.01, 0.02, 0.0]
    shifted = [value + 0.001 for value in returns]

    assert sharpe_ratio(shifted, 0.001, 365.0) == pytest.approx(sharpe_ratio(returns, 0.0, 365.0))


def test_sharpe_is_none_for_a_single_observation():
    assert sharpe_ratio([0.01], 0.0, 365.0) is None


def test_sharpe_is_none_for_constant_returns():
    assert sharpe_ratio([0.01, 0.01, 0.01], 0.0, 365.0) is None


def test_sharpe_rejects_a_nan_input():
    with pytest.raises(ValueError):
        sharpe_ratio([0.01, math.nan], 0.0, 365.0)


def test_sharpe_rejects_an_infinite_input():
    with pytest.raises(ValueError):
        sharpe_ratio([0.01, math.inf], 0.0, 365.0)


def test_sortino_matches_the_hand_computed_value():
    returns = [0.01, -0.01, 0.02, 0.0]
    expected = (0.005 / 0.005) * math.sqrt(365.0)

    assert sortino_ratio(returns, 0.0, 365.0) == pytest.approx(expected)


def test_sortino_uses_every_observation_in_the_downside_denominator():
    returns = [0.02, 0.02, -0.01, 0.02]
    mean = sum(returns) / 4.0
    downside = math.sqrt((0.01**2) / 4.0)
    expected = (mean / downside) * math.sqrt(365.0)

    assert sortino_ratio(returns, 0.0, 365.0) == pytest.approx(expected)


def test_sortino_is_none_without_any_downside():
    assert sortino_ratio([0.01, 0.02], 0.0, 365.0) is None


def test_sortino_is_none_for_a_single_observation():
    assert sortino_ratio([-0.01], 0.0, 365.0) is None


def test_win_rate_counts_the_strictly_positive_r():
    assert win_rate([2.0, -1.0, 0.0, 1.5]) == pytest.approx(0.5)


def test_win_rate_is_none_for_an_empty_input():
    assert win_rate([]) is None


def test_profit_factor_is_the_gains_over_the_losses():
    assert profit_factor([2.0, -1.0, 1.0, -0.5]) == pytest.approx(3.0 / 1.5)


def test_profit_factor_is_none_without_losses():
    assert profit_factor([1.0, 2.0]) is None


def test_expectancy_is_the_mean_r():
    assert expectancy([2.0, -1.0, 0.0]) == pytest.approx(1.0 / 3.0)


def test_expectancy_is_none_for_an_empty_input():
    assert expectancy([]) is None
