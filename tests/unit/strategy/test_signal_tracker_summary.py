"""Characterization of the tracker performance summary.

The keys `total`, `win_rate` and `pending` are a live contract: the Telegram
`/performance` command renders them. Phase 3 adds a separate `no_data` key
but must not change these three.
"""

from datetime import UTC, datetime

from strategy.signal_tracker import SignalTracker


def _details(symbol: str = "BTC/USDT") -> dict:
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "signal_type": "buy",
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "created_at": datetime(2026, 10, 1, 10, tzinfo=UTC).isoformat(),
        "candle_time": datetime(2026, 10, 1, 9, tzinfo=UTC).isoformat(),
    }


async def test_summary_counts_resolved_signals_win_rate_and_pending(tmp_path):
    tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
    await tracker.record("sig-win", True, _details())
    await tracker.record("sig-loss", False, _details())
    await tracker.record("sig-pending", None, _details())

    summary = tracker.get_performance_summary()

    assert summary["total"] == 2
    assert summary["win_rate"] == 50.0
    assert summary["pending"] == 1


async def test_summary_of_an_empty_tracker_reports_zero_and_all_pending(tmp_path):
    tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))

    summary = tracker.get_performance_summary()

    assert summary["total"] == 0
    assert summary["win_rate"] == 0.0
    assert summary["pending"] == 0


async def test_summary_keeps_the_three_contract_keys(tmp_path):
    tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
    await tracker.record("sig-win", True, _details())

    summary = tracker.get_performance_summary()

    for key in ("total", "win_rate", "pending"):
        assert key in summary
