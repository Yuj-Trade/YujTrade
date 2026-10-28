from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from backtesting.historical_signals import (
    candles_from_frame,
    generate_historical_signals,
    simulator_inputs_from_signals,
    trade_metrics,
)


def make_frame(rows: int = 200, timeframe: str = "1M") -> pd.DataFrame:
    freq = {"1M": "MS", "1h": "h", "1d": "D"}[timeframe]
    dates = pd.date_range("2024-01-01", periods=rows, freq=freq, tz="UTC")
    prices = 200.0 - 0.01 * __import__("numpy").arange(rows)
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices + 1.0,
            "low": prices - 1.0,
            "close": prices * 0.999,
            "volume": [10.0] * rows,
        },
        index=dates,
    )


def make_signal(symbol="BTC/USDT", timeframe="1M", side="buy"):
    return SimpleNamespace(
        symbol=symbol,
        timeframe=timeframe,
        signal_type=SimpleNamespace(value=side),
        timestamp=datetime(2024, 2, 1, tzinfo=UTC),
        stop_loss=99.0,
        exit_price=105.0,
    )


async def test_generator_none_counts_rejections():
    generator = MagicMock()
    generator.generate_signal = AsyncMock(return_value=None)
    signals, rejected = await generate_historical_signals(
        make_frame(200), "BTC/USDT", "1M", generator
    )
    assert signals == []
    assert rejected["no_signal"] == 50
    assert rejected["errors"] == 0


async def test_generator_error_counts_rejections():
    generator = MagicMock()
    generator.generate_signal = AsyncMock(side_effect=RuntimeError("boom"))
    signals, rejected = await generate_historical_signals(
        make_frame(200), "BTC/USDT", "1M", generator
    )
    assert signals == []
    assert rejected["errors"] == 50


async def test_generator_signals_are_collected():
    signal = make_signal()
    generator = MagicMock()
    generator.generate_signal = AsyncMock(return_value=signal)
    signals, rejected = await generate_historical_signals(
        make_frame(200), "BTC/USDT", "1M", generator
    )
    assert signals == [signal] * 50
    assert rejected["no_signal"] == 0
    assert rejected["errors"] == 0


async def test_step_skips_windows():
    generator = MagicMock()
    generator.generate_signal = AsyncMock(return_value=None)
    await generate_historical_signals(make_frame(200), "BTC/USDT", "1M", generator, step=10)
    assert generator.generate_signal.await_count == 5


async def test_include_flags_forwarded():
    generator = MagicMock()
    generator.generate_signal = AsyncMock(return_value=None)
    await generate_historical_signals(
        make_frame(200),
        "BTC/USDT",
        "1M",
        generator,
        include_external=True,
        include_ml=True,
    )
    kwargs = generator.generate_signal.await_args.kwargs
    assert kwargs["include_external"] is True
    assert kwargs["include_ml"] is True


async def test_window_end_is_inclusive_prefix():
    seen = []

    async def generate(symbol, timeframe, window, **kwargs):
        seen.append(len(window))
        return None

    generator = MagicMock()
    generator.generate_signal = generate
    await generate_historical_signals(make_frame(200), "BTC/USDT", "1M", generator)
    assert seen == list(range(151, 201))


async def test_empty_frame_returns_empty():
    generator = MagicMock()
    generator.generate_signal = AsyncMock(return_value=None)
    signals, rejected = await generate_historical_signals(
        make_frame(200).iloc[:0], "BTC/USDT", "1M", generator
    )
    assert signals == []
    assert rejected == {"no_signal": 0, "errors": 0}


def test_candles_from_frame_converts_rows():
    rows = candles_from_frame(make_frame(3))
    assert len(rows) == 3
    first = rows[0]
    assert set(first) == {"timestamp", "open", "high", "low", "close", "volume"}
    assert isinstance(first["timestamp"], datetime)
    assert first["open"] == pytest.approx(200.0)
    assert first["close"] == pytest.approx(200.0 * 0.999)


def test_simulator_inputs_from_signals_builds_ids():
    inputs = simulator_inputs_from_signals([make_signal()])
    assert len(inputs) == 1
    entry = inputs[0]
    assert entry["side"] == "buy"
    assert entry["signal_id"] == "BTC/USDT|1M|2024-02-01T00:00:00+00:00|buy"
    assert entry["stop"] == 99.0
    assert entry["target"] == 105.0
    assert isinstance(entry["timestamp"], datetime)


def test_simulator_inputs_from_signals_handles_pandas_timestamp():
    signal = make_signal()
    signal.timestamp = pd.Timestamp("2024-02-01T00:00:00Z")
    inputs = simulator_inputs_from_signals([signal])
    assert isinstance(inputs[0]["timestamp"], datetime)


def test_trade_metrics_empty_trades():
    metrics = trade_metrics([], 1000.0)
    assert metrics["trades_count"] == 0
    assert metrics["win_rate"] == 0.0
    assert metrics["profit_factor"] == 0.0
    assert metrics["max_drawdown"] == 0.0
    assert metrics["sharpe"] == 0.0
    assert metrics["final_equity"] == 1000.0


def test_trade_metrics_counts_wins():
    trades = [SimpleNamespace(pnl=10.0), SimpleNamespace(pnl=-5.0), SimpleNamespace(pnl=20.0)]
    metrics = trade_metrics(trades, 1000.0)
    assert metrics["trades_count"] == 3
    assert metrics["win_rate"] == pytest.approx(2 / 3)
    assert metrics["profit_factor"] == pytest.approx(30.0 / 5.0)
    assert metrics["final_equity"] == pytest.approx(1025.0)


def test_trade_metrics_drawdown_tracking():
    trades = [SimpleNamespace(pnl=100.0), SimpleNamespace(pnl=-150.0)]
    metrics = trade_metrics(trades, 1000.0)
    assert metrics["max_drawdown"] == pytest.approx(150.0 / 1100.0)
    assert metrics["final_equity"] == pytest.approx(950.0)


def test_trade_metrics_sharpe_zero_for_single_trade():
    metrics = trade_metrics([SimpleNamespace(pnl=10.0)], 1000.0)
    assert metrics["sharpe"] == 0.0


def test_trade_metrics_sharpe_finite():
    trades = [SimpleNamespace(pnl=pnl) for pnl in (10.0, -4.0, 6.0, -2.0)]
    metrics = trade_metrics(trades, 1000.0)
    assert metrics["sharpe"] != 0.0
    assert metrics["sharpe"] == metrics["sharpe"]


def test_trade_metrics_all_losses_profit_factor_zero():
    trades = [SimpleNamespace(pnl=-10.0), SimpleNamespace(pnl=-5.0)]
    metrics = trade_metrics(trades, 1000.0)
    assert metrics["profit_factor"] == 0.0
    assert metrics["win_rate"] == 0.0
