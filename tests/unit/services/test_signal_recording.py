"""The recording of a signal in the analysis path.

A signal id is derived from the candle index, so the same open signal is
produced again on every analysis cycle. The recording must therefore not
rewrite the first creation, the first levels or the notification state of
an entry that already exists.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from common.core import SignalType, TradingSignal
from config.logger import logger as root_logger
from services.trading_service import TradingService
from strategy.signal_tracker import SignalTracker, make_signal_id


def _signal(**overrides) -> TradingSignal:
    base = {
        "symbol": "BTC/USDT",
        "signal_type": SignalType.BUY,
        "entry_price": 200.0,
        "exit_price": 210.0,
        "stop_loss": 195.0,
        "timestamp": datetime(2026, 10, 1, 10, tzinfo=UTC),
        "timeframe": "1h",
        "confidence_score": 90.0,
        "reasons": ["trend up"],
        "risk_reward_ratio": 3.0,
        "predicted_profit": 10.0,
        "volume_analysis": {"volume_ratio": 2.0},
        "market_context": {"trend_strength": "STRONG"},
        "dynamic_levels": {},
    }
    base.update(overrides)
    return TradingSignal(**base)


def _service(tracker, signal) -> TradingService:
    service = TradingService.__new__(TradingService)
    service.invalid_symbols = set()
    service._cycle_log = root_logger.bind(run_id="record-test")
    service.market_data_provider = SimpleNamespace(
        fetch_ohlcv_data=AsyncMock(return_value=MagicMock(empty=False))
    )
    generator = MagicMock()
    generator.generate_signal = AsyncMock(return_value=signal)
    service.signal_generator = generator
    confirmation = MagicMock()
    confirmation.get_confirmation_score = AsyncMock(return_value=(0.9, None, False))
    service.multi_tf_analyzer = confirmation
    service.signal_tracker = tracker
    return service


async def test_reopened_open_signal_keeps_first_creation_and_levels(tmp_path):
    tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
    signal = _signal()
    signal_id = make_signal_id(
        signal.symbol, signal.timeframe, signal.timestamp, signal.signal_type.value
    )
    first_created_at = datetime(2026, 10, 1, 10, tzinfo=UTC).isoformat()
    await tracker.record(
        signal_id,
        None,
        {
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "signal_type": signal.signal_type.value,
            "entry": 100.0,
            "stop": 95.0,
            "target": 110.0,
            "created_at": first_created_at,
            "notification_state": "pending",
        },
    )
    service = _service(tracker, signal)

    await service.analyze_symbol("BTC/USDT", "1h")

    details = tracker.history[signal_id]["details"]
    assert details["created_at"] == first_created_at
    assert details["entry"] == 100.0
    assert details["stop"] == 95.0
    assert details["target"] == 110.0
    assert details["notification_state"] == "pending"


async def test_a_new_signal_is_recorded_once(tmp_path):
    tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
    signal = _signal()
    signal_id = make_signal_id(
        signal.symbol, signal.timeframe, signal.timestamp, signal.signal_type.value
    )
    service = _service(tracker, signal)

    await service.analyze_symbol("BTC/USDT", "1h")
    await service.analyze_symbol("BTC/USDT", "1h")

    assert list(tracker.history) == [signal_id]
    assert tracker.history[signal_id]["outcome"] is None
