"""The outcome watch: the observation of the open signals on closed candles.

The watch is independent of the analysis cycle: the expired signals settle
and the open signals are observed on the closed candles, so a target or a
stop that is touched before the expiry is reported.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd

from application.outcome_policy import NotificationPolicy
from services.trading_service import TradingService
from strategy.signal_tracker import SignalTracker

_ONE_HOUR = timedelta(hours=1)


def _policy(**overrides) -> NotificationPolicy:
    base = {
        "mode": "live",
        "kinds": frozenset({"target", "stop", "expired"}),
        "timeframes": frozenset({"1h"}),
        "since": None,
        "max_attempts": 3,
        "claim_ttl": timedelta(minutes=5),
        "watch_interval": timedelta(minutes=15),
        "concurrency": 2,
    }
    base.update(overrides)
    return NotificationPolicy(**base)


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


def _provider(frame):
    return SimpleNamespace(fetch_ohlcv_data=AsyncMock(return_value=frame))


class TestOutcomeWatch:
    async def test_a_target_before_the_expiry_is_observed(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=2)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame(
            [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
            created,
        )
        service = _service(tracker, _provider(frame))

        report = await service.watch_outcomes(_policy(), now)

        assert report.detected == 1
        assert report.groups == 1
        assert report.failed_groups == 0
        details = tracker.history["sig-1"]["details"]
        assert details["outcome_event"] == "target"
        assert details["outcome_event_price"] == 110.0
        assert details["notification_state"] == "pending"

    async def test_the_observation_does_not_change_the_outcome(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=2)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame(
            [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
            created,
        )
        service = _service(tracker, _provider(frame))

        await service.watch_outcomes(_policy(), now)

        assert tracker.history["sig-1"]["outcome"] is None
        assert "resolved_price" not in tracker.history["sig-1"]["details"]

    async def test_the_observation_does_not_write_the_ledger(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=2)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame(
            [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
            created,
        )
        service = _service(tracker, _provider(frame))
        ledger = MagicMock()
        ledger.has_resolution = AsyncMock(return_value=False)
        ledger.record_resolution = AsyncMock(return_value=True)
        service.performance_ledger = ledger
        service._performance_ledger_enabled = True

        await service.watch_outcomes(_policy(), now)

        ledger.record_resolution.assert_not_called()

    async def test_an_expired_signal_settles_without_an_analysis_cycle(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=13)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame([(101.0, 99.0, 100.0)] * 13, created)
        service = _service(tracker, _provider(frame))

        report = await service.watch_outcomes(_policy(), now)

        assert report.settled == 1
        assert tracker.history["sig-1"]["outcome"] is False
        assert tracker.history["sig-1"]["details"]["resolution_status"] == "expired"

    async def test_the_expiry_registers_the_first_touch_only_once(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=13)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame(
            [(112.0, 101.0, 110.0)] + [(101.0, 99.0, 100.0)] * 12,
            created,
        )
        service = _service(tracker, _provider(frame))

        report = await service.watch_outcomes(_policy(), now)

        assert report.settled == 1
        details = tracker.history["sig-1"]["details"]
        assert details["outcome_event"] == "target"
        assert details["outcome_event_price"] == 110.0

    async def test_a_failing_group_does_not_stop_the_other_groups(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=2)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-btc", None, _details(created, symbol="BTC/USDT"))
        await tracker.record("sig-eth", None, _details(created, symbol="ETH/USDT"))
        frame = _frame(
            [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
            created,
        )

        async def fetch(symbol, timeframe, limit=1000, bypass_cache=False):
            if symbol == "BTC/USDT":
                raise RuntimeError("exchange down")
            return frame

        provider = SimpleNamespace(fetch_ohlcv_data=AsyncMock(side_effect=fetch))
        service = _service(tracker, provider)

        report = await service.watch_outcomes(_policy(), now)

        assert report.failed_groups == 1
        assert report.detected == 1
        assert tracker.history["sig-eth"]["details"]["outcome_event"] == "target"
        assert "outcome_event" not in tracker.history["sig-btc"]["details"]

    async def test_three_signals_of_one_group_use_one_fetch(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=2)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        for index in range(3):
            await tracker.record(f"sig-{index}", None, _details(created))
        frame = _frame(
            [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
            created,
        )
        provider = _provider(frame)
        service = _service(tracker, provider)

        report = await service.watch_outcomes(_policy(), now)

        assert provider.fetch_ohlcv_data.await_count == 1
        assert report.groups == 1
        assert report.detected == 3

    async def test_the_last_open_candle_is_not_used(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=2)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame(
            [(101.0, 99.0, 100.0), (101.0, 99.0, 100.0), (112.0, 101.0, 110.0)],
            created,
        )
        service = _service(tracker, _provider(frame))

        report = await service.watch_outcomes(_policy(), now)

        assert report.detected == 0
        assert "outcome_event" not in tracker.history["sig-1"]["details"]

    async def test_the_signals_before_the_since_bound_are_not_observed(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=3)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        frame = _frame(
            [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
            created,
        )
        service = _service(tracker, _provider(frame))

        report = await service.watch_outcomes(_policy(since=now - timedelta(hours=1)), now)

        assert report.detected == 0
        assert report.groups == 0

    async def test_an_unknown_timeframe_is_not_observed(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=1)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created, timeframe="9h"))
        service = _service(tracker, _provider(_frame([(101.0, 99.0, 100.0)], created)))

        report = await service.watch_outcomes(_policy(), now)

        assert report.detected == 0
        assert report.groups == 0

    async def test_a_resolved_signal_is_not_observed_again(self, tmp_path):
        now = datetime.now(UTC)
        created = now - timedelta(hours=2)
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        await tracker.record("sig-1", None, _details(created))
        await tracker.resolve("sig-1", True, {"resolved_price": 110.0})
        frame = _frame(
            [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
            created,
        )
        service = _service(tracker, _provider(frame))

        report = await service.watch_outcomes(_policy(), now)

        assert report.detected == 0
        assert report.groups == 0
