"""The v2 simulator branch: per-leg cost, partial fill, funding, unfilled."""

from datetime import UTC, datetime, timedelta

import pytest

from backtesting.simulator import EventDrivenSimulator, SimulatorConfig
from domain.costs import CostProfile, legacy_simulator_profile, net_r

BASE = datetime(2025, 1, 1, tzinfo=UTC)

PROFILE = CostProfile(
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


def _candle(index, open_, high, low, close=None, volume=1000.0):
    return {
        "timestamp": BASE + timedelta(hours=index),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close if close is not None else open_),
        "volume": float(volume),
    }


def _signal(index=0, side="buy", stop=95.0, target=120.0):
    return {
        "signal_id": f"sig-{index}",
        "side": side,
        "timestamp": BASE + timedelta(hours=index),
        "stop": float(stop),
        "target": float(target),
    }


def _full_quantity(entry: float, stop: float, equity: float) -> float:
    from domain.sizing import SizingConfig, calculate_position_size

    sizing = SizingConfig(1.0, 10.0, 60.0, 3.0)
    return calculate_position_size(equity, entry, stop, sizing).quantity


def _v2() -> EventDrivenSimulator:
    return EventDrivenSimulator(SimulatorConfig(cost_profile=PROFILE))


def test_the_v2_r_multiple_matches_the_domain_formula():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 100.5, 125, 100),
        _candle(3, 101, 102, 100),
    ]
    trades, stats = _v2().run_with_stats(candles, [_signal()], 10000.0)

    assert len(trades) == 1
    trade = trades[0]
    holding = (trade.exit_time - trade.entry_time).total_seconds() / 3600.0
    expected = net_r(
        100.0,
        95.0,
        trade.exit_price,
        "buy",
        trade.exit_reason,
        holding,
        PROFILE,
        1.0,
    )
    assert trade.r_multiple == pytest.approx(expected)


def test_the_v2_r_multiple_matches_net_r_on_random_permutations():
    import random

    rng = random.Random(20261029)
    for _ in range(20):
        entry = rng.uniform(50.0, 200.0)
        stop = entry * (1.0 - rng.uniform(0.01, 0.05))
        target = entry * (1.0 + rng.uniform(0.02, 0.1))
        candles = [
            _candle(0, entry - 0.5, entry, entry - 1.0),
            _candle(1, entry, entry + 0.5, entry - 0.5),
            _candle(2, entry, max(target * 1.01, entry + 1.0), min(stop * 0.99, entry - 1.0)),
            _candle(3, entry, entry + 0.5, entry - 0.5),
        ]
        trades, _ = _v2().run_with_stats(candles, [_signal(stop=stop, target=target)], 100000.0)
        assert len(trades) == 1
        trade = trades[0]
        holding = (trade.exit_time - trade.entry_time).total_seconds() / 3600.0
        expected = net_r(
            entry,
            stop,
            trade.exit_price,
            trade.side,
            trade.exit_reason,
            holding,
            PROFILE,
            trade.qty / _full_quantity(entry, stop, 100000.0),
        )
        assert trade.r_multiple == pytest.approx(expected)


def test_a_partial_fill_reduces_the_quantity():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100, volume=1.0),
        _candle(2, 100.5, 125, 100),
        _candle(3, 101, 102, 100),
    ]
    full_candles = [dict(item) for item in candles]
    full_candles[1]["volume"] = 1e9

    partial, _ = _v2().run_with_stats(candles, [_signal()], 10000.0)
    full, _ = _v2().run_with_stats(full_candles, [_signal()], 10000.0)

    assert len(partial) == 1
    assert partial[0].qty < full[0].qty
    assert partial[0].qty == pytest.approx(full[0].qty * 0.05 * 100.0 / (full[0].qty * 100.0))


def test_a_zero_volume_is_counted_as_unfilled():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100, volume=0.0),
        _candle(2, 100.5, 125, 100),
    ]
    trades, stats = _v2().run_with_stats(candles, [_signal()], 10000.0)

    assert trades == []
    assert stats.skipped_unfilled == 1


def test_funding_is_included_in_the_fee():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 100.5, 125, 100),
    ]
    no_funding_profile = CostProfile(**{**PROFILE.__dict__, "funding_rate_per_period": 0.0})
    funded, _ = _v2().run_with_stats(candles, [_signal()], 10000.0)
    unfunded, _ = EventDrivenSimulator(
        SimulatorConfig(cost_profile=no_funding_profile)
    ).run_with_stats(candles, [_signal()], 10000.0)

    assert funded[0].fee > unfunded[0].fee


def test_the_legacy_branch_is_unchanged_on_a_fixture():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 100.5, 91, 89),
    ]
    legacy = EventDrivenSimulator(
        SimulatorConfig(cost_profile=legacy_simulator_profile(0.001, 0.0005))
    )
    implicit = EventDrivenSimulator(SimulatorConfig())

    first, _ = legacy.run_with_stats(candles, [_signal()], 10000.0)
    second, _ = implicit.run_with_stats(candles, [_signal()], 10000.0)

    assert first == second
    assert first[0].entry_price == pytest.approx(100.05)
    assert first[0].exit_price == pytest.approx(95.0)


def test_the_stats_carry_the_unfilled_field():
    _, stats = EventDrivenSimulator().run_with_stats([], [], 10000.0)
    assert stats.skipped_unfilled == 0


def test_a_maker_target_is_not_slipped_in_v2():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 100.5, 125, 100),
    ]
    trades, _ = _v2().run_with_stats(candles, [_signal()], 10000.0)

    assert trades[0].exit_reason == "target"
    assert trades[0].exit_price == pytest.approx(120.0)
