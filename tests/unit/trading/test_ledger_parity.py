"""Ledger parity with the domain outcome contract and mark-price valuation.

The simulator resolves exits through `domain.outcome.resolve_outcome`; the
paper ledger must agree with that same contract for an identical candle
sequence (FakeAdapter style: no network, no exchange).
"""

from datetime import datetime, timedelta, timezone

from backtesting.simulator import EventDrivenSimulator, SimulatorConfig
from domain.outcome import resolve_outcome
from trading.ledger import PaperLedger


def _ledger(tmp_path) -> PaperLedger:
    return PaperLedger(tmp_path / "paper_ledger.db")


def _candles():
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    opens = [99.0, 100.0, 101.0, 102.0]
    highs = [99.5, 112.0, 103.0, 104.0]
    lows = [98.5, 101.0, 100.5, 101.5]
    return [
        {
            "timestamp": base + timedelta(hours=i),
            "open": opens[i],
            "high": highs[i],
            "low": lows[i],
            "close": (opens[i] + highs[i]) / 2,
        }
        for i in range(4)
    ]


def test_duplicate_signal_id_rejected_and_recorded(tmp_path):
    ledger = _ledger(tmp_path)
    first = ledger.append_order("sig-1", "BTC/USDT", "buy", 2.0)
    second = ledger.append_order("sig-1", "BTC/USDT", "buy", 2.0)
    assert isinstance(first, int)
    assert second is None
    count = ledger.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert count == 1
    ledger.close()


def test_resolution_matches_simulator_for_same_candles():
    candles = _candles()
    window = candles[1:]
    expected = resolve_outcome(window, "buy", 100.0, 95.0, 110.0)
    assert expected is not None
    assert (expected.success, expected.exit_price, expected.reason) == (
        True,
        110.0,
        "target",
    )

    simulator = EventDrivenSimulator(SimulatorConfig(slippage_rate=0.0, commission_rate=0.0))
    signals = [
        {
            "signal_id": "sig-1",
            "side": "buy",
            "timestamp": candles[0]["timestamp"],
            "stop": 95.0,
            "target": 110.0,
        }
    ]
    trades = simulator.run(candles, signals, equity=100_000.0)
    assert len(trades) == 1
    assert trades[0].exit_reason == expected.reason
    assert trades[0].exit_price == expected.exit_price


def test_equity_uses_mark_price_and_flags_stale(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.connection.execute(
        "INSERT INTO positions(symbol, side, quantity, entry_price) VALUES (?, ?, ?, ?)",
        ("BTC/USDT", "buy", 1.0, 100.0),
    )
    positions = [
        {
            "id": 1,
            "symbol": "BTC/USDT",
            "side": "buy",
            "quantity": 1.0,
            "entry_price": 100.0,
        }
    ]
    equity = ledger.snapshot_equity(9000.0, positions, {"BTC/USDT": 110.0})
    assert equity == 9010.0
    stale = ledger.connection.execute("SELECT stale FROM positions WHERE id = 1")
    assert stale.fetchone()[0] == 0

    equity_missing = ledger.snapshot_equity(9000.0, positions, {})
    assert equity_missing == 9000.0
    stale = ledger.connection.execute("SELECT stale FROM positions WHERE id = 1")
    assert stale.fetchone()[0] == 1
    ledger.close()
