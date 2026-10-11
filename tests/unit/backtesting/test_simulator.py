from datetime import datetime, timedelta, timezone

import pytest

from backtesting.simulator import (
    EventDrivenSimulator,
    SimulatorConfig,
    write_trades_csv,
)

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candle(index, open, high, low, close=None):
    return {
        "timestamp": BASE + timedelta(hours=index),
        "open": float(open),
        "high": float(high),
        "low": float(low),
        "close": float(close if close is not None else open),
        "volume": 1000.0,
    }


def _signal(index=0, side="buy", stop=95.0, target=120.0):
    return {
        "signal_id": f"sig-{index}",
        "side": side,
        "timestamp": BASE + timedelta(hours=index),
        "stop": float(stop),
        "target": float(target),
    }


def test_stop_only_fill_is_exact():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 100.5, 101, 90),
    ]
    trades, stats = EventDrivenSimulator().run_with_stats(candles, [_signal()], 10000.0)
    assert stats.signals_evaluated == 1
    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_reason == "stop"
    assert trade.qty == 9
    assert trade.entry_price == pytest.approx(100.05)
    assert trade.exit_price == pytest.approx(95.0)
    assert trade.fee == pytest.approx(1.75545)
    assert trade.pnl == pytest.approx(-47.20545)


def test_target_only_fill_is_exact():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 100.5, 125, 100),
    ]
    trades, _ = EventDrivenSimulator().run_with_stats(candles, [_signal()], 10000.0)
    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_reason == "target"
    assert trade.exit_price == pytest.approx(120.0)
    assert trade.fee == pytest.approx(1.98045)
    assert trade.pnl == pytest.approx(177.56955)


def test_stop_wins_when_both_hit_in_one_candle():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 100.5, 130, 90),
    ]
    trades, _ = EventDrivenSimulator().run_with_stats(candles, [_signal()], 10000.0)
    assert len(trades) == 1
    assert trades[0].exit_reason == "stop"
    assert trades[0].exit_price == pytest.approx(95.0)


def test_gap_beyond_stop_exits_at_open():
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 90, 91, 89),
    ]
    trades, _ = EventDrivenSimulator().run_with_stats(candles, [_signal()], 10000.0)
    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_reason == "stop"
    assert trade.exit_price == pytest.approx(90.0)
    assert trade.pnl == pytest.approx(-92.16045)


def test_zero_quantity_is_counted_as_size_zero():
    candles = [_candle(0, 99, 100, 98), _candle(1, 100, 101, 100)]
    entry = 100.0 * (1.0 + SimulatorConfig().slippage_rate)
    trades, stats = EventDrivenSimulator().run_with_stats(
        candles, [_signal(stop=entry)], 10000.0
    )
    assert trades == []
    assert stats.skipped_size_zero == 1


def test_unknown_signal_time_is_counted_as_no_window():
    candles = [_candle(0, 99, 100, 98), _candle(1, 100, 101, 100)]
    orphan = dict(_signal(index=9))
    trades, stats = EventDrivenSimulator().run_with_stats(candles, [orphan], 10000.0)
    assert trades == []
    assert stats.skipped_no_window == 1


def test_run_matches_run_with_stats_trades(tmp_path):
    candles = [
        _candle(0, 99, 100, 98),
        _candle(1, 100, 101, 100),
        _candle(2, 100.5, 125, 100),
    ]
    simulator = EventDrivenSimulator()
    assert simulator.run(candles, [_signal()], 10000.0) == simulator.run_with_stats(
        candles, [_signal()], 10000.0
    )[0]
    out = tmp_path / "trades.csv"
    write_trades_csv(out, simulator.run(candles, [_signal()], 10000.0))
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == (
        "signal_id,side,entry_time,entry_price,exit_time,exit_price,"
        "exit_reason,qty,fee,pnl,r_multiple"
    )
