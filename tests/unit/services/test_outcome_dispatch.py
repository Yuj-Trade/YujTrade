from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd

from application.outcome_policy import NotificationPolicy
from application.outcome_ports import NotificationDeliveryError
from services.outcome_dispatch import dispatch_outcomes
from strategy.signal_tracker import SignalTracker

_CREATED_AT = datetime(2026, 10, 1, 10, tzinfo=UTC)
_EVENT_AT = datetime(2026, 10, 1, 14, tzinfo=UTC)
_ONE_HOUR = timedelta(hours=1)


def _frame(rows, start: datetime):
    return pd.DataFrame(
        [{"open": close, "high": high, "low": low, "close": close} for high, low, close in rows],
        index=[start + _ONE_HOUR * index for index in range(len(rows))],
    )


@dataclass
class _FakeNotifier:
    sent: list[str]
    error: Exception | None = None

    async def send(self, text: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(text)


def _policy(**overrides) -> NotificationPolicy:
    base = {
        "mode": "live",
        "kinds": frozenset({"target", "stop", "expired"}),
        "timeframes": frozenset({"1h"}),
        "since": None,
        "max_attempts": 3,
        "claim_ttl": timedelta(minutes=5),
        "watch_interval": timedelta(minutes=15),
        "concurrency": 4,
    }
    base.update(overrides)
    return NotificationPolicy(**base)


def _details(**overrides) -> dict:
    base = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "signal_type": "buy",
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "created_at": _CREATED_AT.isoformat(),
    }
    base.update(overrides)
    return base


async def _tracker(tmp_path, **overrides) -> SignalTracker:
    from domain.outcome import OutcomeEvent

    tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
    await tracker.record("sig-1", None, _details(**overrides))
    event = OutcomeEvent("sig-1", "target", 110.0, _EVENT_AT)
    await tracker.set_outcome_event("sig-1", event)
    return tracker


async def test_a_successful_delivery_is_sent_and_completed(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[])

    report = await dispatch_outcomes(tracker, notifier, _policy(), _EVENT_AT)

    assert report.sent == 1
    assert report.retried == 0
    assert report.abandoned == 0
    assert len(notifier.sent) == 1
    assert "TP hit" in notifier.sent[0]
    assert tracker.history["sig-1"]["details"]["notification_state"] == "sent"


async def test_a_permanent_error_is_abandoned_immediately(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[], error=NotificationDeliveryError("bad", permanent=True))

    report = await dispatch_outcomes(tracker, notifier, _policy(), _EVENT_AT)

    assert report.abandoned == 1
    assert report.retried == 0
    assert notifier.sent == []
    assert tracker.history["sig-1"]["details"]["notification_state"] == "abandoned"
    assert tracker.history["sig-1"]["details"]["notification_attempts"] == 1


async def test_a_retryable_error_stays_pending_until_the_limit(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[], error=NotificationDeliveryError("later", permanent=False))

    first = await dispatch_outcomes(tracker, notifier, _policy(), _EVENT_AT)
    assert first.retried == 1
    assert tracker.history["sig-1"]["details"]["notification_state"] == "pending"
    assert tracker.history["sig-1"]["details"]["notification_attempts"] == 1

    await dispatch_outcomes(tracker, notifier, _policy(), _EVENT_AT + timedelta(minutes=1))
    assert tracker.history["sig-1"]["details"]["notification_attempts"] == 2

    last = await dispatch_outcomes(tracker, notifier, _policy(), _EVENT_AT + timedelta(minutes=2))
    assert last.abandoned == 1
    assert tracker.history["sig-1"]["details"]["notification_state"] == "abandoned"
    assert tracker.history["sig-1"]["details"]["notification_attempts"] == 3


async def test_an_unexpected_error_is_treated_as_retryable(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[], error=RuntimeError("boom"))

    report = await dispatch_outcomes(tracker, notifier, _policy(), _EVENT_AT)

    assert report.retried == 1
    assert tracker.history["sig-1"]["details"]["notification_state"] == "pending"


async def test_the_shadow_mode_never_calls_the_notifier(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[])

    report = await dispatch_outcomes(tracker, notifier, _policy(mode="shadow"), _EVENT_AT)

    assert report.shadowed == 1
    assert report.sent == 0
    assert notifier.sent == []
    assert tracker.history["sig-1"]["details"]["notification_state"] == "shadowed"


async def test_an_ineligible_kind_is_suppressed(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[])

    report = await dispatch_outcomes(
        tracker, notifier, _policy(kinds=frozenset({"stop"})), _EVENT_AT
    )

    assert report.suppressed == 1
    assert notifier.sent == []
    assert tracker.history["sig-1"]["details"]["notification_state"] == "suppressed"


async def test_a_signal_before_the_since_bound_is_suppressed(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[])

    report = await dispatch_outcomes(
        tracker,
        notifier,
        _policy(since=_CREATED_AT + timedelta(hours=1)),
        _EVENT_AT,
    )

    assert report.suppressed == 1
    assert notifier.sent == []


async def test_a_claimed_notification_is_not_sent_twice(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[])
    now = datetime.now(UTC)
    assert await tracker.claim_notification("sig-1", now, timedelta(minutes=5)) is True

    report = await dispatch_outcomes(tracker, notifier, _policy(), now)

    assert report.sent == 0
    assert notifier.sent == []


async def test_a_terminal_notification_is_not_sent_again(tmp_path):
    tracker = await _tracker(tmp_path)
    notifier = _FakeNotifier(sent=[])
    await dispatch_outcomes(tracker, notifier, _policy(), _EVENT_AT)

    report = await dispatch_outcomes(tracker, notifier, _policy(), _EVENT_AT + timedelta(minutes=1))

    assert report.sent == 0
    assert len(notifier.sent) == 1


async def test_a_missing_notifier_leaves_the_notification_pending(tmp_path):
    tracker = await _tracker(tmp_path)

    report = await dispatch_outcomes(tracker, None, _policy(), _EVENT_AT)

    assert report.sent == 0
    assert tracker.history["sig-1"]["details"]["notification_state"] == "pending"


async def test_the_sequence_watch_dispatch_and_reload_sends_once(tmp_path):
    from datetime import UTC

    from application.outcome_policy import build_policy
    from common.constants import TIME_FRAMES
    from services.trading_service import TradingService

    now = datetime.now(UTC)
    created = now - timedelta(hours=2)
    path = tmp_path / "signal_history.json"
    tracker = SignalTracker(storage_path=str(path))
    await tracker.record(
        "sig-1",
        None,
        _details(created_at=created.isoformat()),
    )
    service = TradingService.__new__(TradingService)
    service.signal_tracker = tracker
    service._performance_ledger_enabled = False
    service._cycle_log = MagicMock()
    frame = _frame(
        [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)],
        created,
    )
    service.market_data_provider = SimpleNamespace(fetch_ohlcv_data=AsyncMock(return_value=frame))
    notifier = _FakeNotifier(sent=[])

    policy = build_policy(
        {
            "outcome_notifications_mode": "live",
            "outcome_notifications_since": "2026-01-01T00:00:00+00:00",
        },
        frozenset(TIME_FRAMES),
    )

    report = await service.watch_outcomes(policy, now)
    first = await dispatch_outcomes(tracker, notifier, policy, now)

    assert report.detected == 1
    assert first.sent == 1
    assert len(notifier.sent) == 1

    second = await dispatch_outcomes(tracker, notifier, policy, now + timedelta(minutes=1))

    assert second.sent == 0
    assert len(notifier.sent) == 1

    restored = SignalTracker(storage_path=str(path))
    third = await dispatch_outcomes(restored, notifier, policy, now + timedelta(minutes=2))

    assert third.sent == 0
    assert len(notifier.sent) == 1
