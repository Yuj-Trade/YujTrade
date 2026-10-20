"""The outcome watch: the observation of the open signals on closed candles.

The defect tests are pinned with a strict `xfail` and leave it in stage 1.
The characterization test stays green and locks the current settlement
behaviour.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from services.trading_service import TradingService
from strategy.signal_tracker import SignalTracker

_ONE_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class _PolicyStub:
    mode: str = "live"
    kinds: frozenset[str] = frozenset({"target", "stop", "expired"})
    timeframes: frozenset[str] = frozenset({"1h"})
    since: datetime | None = None
    max_attempts: int = 3
    claim_ttl: timedelta = timedelta(minutes=5)
    watch_interval: timedelta = timedelta(minutes=15)
    concurrency: int = 2


def _details(created_at: datetime, **overrides) -> dict:
    base = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "signal_type": "buy",
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "created_at": created_at.isoformat(),
        "candle_time": created_at.isoformat(),
    }
    base.update(overrides)
    return base


def _frame(rows, start: datetime):
    return pd.DataFrame(
        [{"open": close, "high": high, "low": low, "close": close} for high, low, close in rows],
        index=[start + _ONE_HOUR * index for index in range(len(rows))],
    )


def _service(tracker, provider) -> TradingService:
    service = TradingService.__new__(TradingService)
    service.signal_tracker = tracker
    service.market_data_provider = provider
    service._cycle_log = MagicMock()
    service._performance_ledger_enabled = False
    service.model_manager = SimpleNamespace(record_signal_performance=AsyncMock())
    threshold_manager = MagicMock()
    threshold_manager.flush = AsyncMock()
    service.signal_generator = SimpleNamespace(threshold_manager=threshold_manager)
    return service


class TestOutcomeWatchDefects:
    """The defects that keep an outcome from being notified."""

    @pytest.mark.xfail(strict=True, reason="D4")
    async def test_target_before_expiry_is_observed(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=2)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame(
            [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
            created,
        )
        provider = SimpleNamespace(fetch_ohlcv_data=AsyncMock(return_value=frame))
        service = _service(tracker, provider)

        report = await service.watch_outcomes(_PolicyStub(), now)

        assert report.detected == 1
        assert tracker.history["sig-1"]["details"]["outcome_event"] == "target"

    @pytest.mark.xfail(strict=True, reason="D5")
    async def test_expired_signal_settles_without_analysis_cycle(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=13)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame([(101.0, 99.0, 100.0)] * 13, created)
        provider = SimpleNamespace(fetch_ohlcv_data=AsyncMock(return_value=frame))
        service = _service(tracker, provider)

        report = await service.watch_outcomes(_PolicyStub(), now)

        assert report.settled == 1
        assert tracker.history["sig-1"]["outcome"] is False


class TestOutcomeWatchCharacterization:
    """The current settlement behaviour that the watch must not break."""

    async def test_reconcile_settles_an_expired_signal_without_an_outcome(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=13)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame([(101.0, 99.0, 100.0)] * 13, created)
        provider = SimpleNamespace(fetch_ohlcv_data=AsyncMock(return_value=frame))
        service = _service(tracker, provider)
        calls: list[str] = []
        original_resolve = tracker.resolve

        async def spy(signal_id, outcome, details=None):
            calls.append(signal_id)
            await original_resolve(signal_id, outcome, details)

        tracker.resolve = spy

        resolved = await service.reconcile_pending_signals()

        assert resolved == 1
        assert calls == ["sig-1"]
        assert tracker.history["sig-1"]["outcome"] is False
        assert tracker.history["sig-1"]["details"]["resolved_price"] == 100.0
        assert tracker.history["sig-1"]["details"]["resolution_status"] == "expired"
