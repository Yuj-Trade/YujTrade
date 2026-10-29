"""Reconciliation order: resolve, then ledger, then tracker.

The ledger write happens before the tracker is synchronised so that a
failed write leaves the signal pending and the next cycle retries it.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from domain.outcome import Resolution
from services.trading_service import TradingService

_CREATED_AT = datetime(2026, 10, 1, 10, tzinfo=UTC)


def _details(**overrides):
    base = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "signal_type": "buy",
        "created_at": _CREATED_AT.isoformat(),
    }
    base.update(overrides)
    return base


def _service(ledger, resolution, tracker=None):
    service = TradingService.__new__(TradingService)
    service._cycle_log = MagicMock()
    service.performance_ledger = ledger
    service._performance_ledger_enabled = True
    service.signal_tracker = tracker or SimpleNamespace(
        get_pending_expired=AsyncMock(return_value=[{"signal_id": "sig-1", "details": _details()}]),
        resolve=AsyncMock(),
        update_resolution_details=AsyncMock(),
        set_outcome_event=AsyncMock(return_value=True),
    )
    service.model_manager = SimpleNamespace(record_signal_performance=AsyncMock())
    service.signal_generator = SimpleNamespace(threshold_manager=MagicMock(flush=AsyncMock()))

    async def fake_resolve(symbol, timeframe, details, created_at, expiry_hours, *, now):
        return resolution

    service._resolve_signal_outcome = fake_resolve
    return service


def _ledger(has_resolution=False, record=True):
    ledger = SimpleNamespace(
        has_resolution=AsyncMock(return_value=has_resolution),
        record_resolution=AsyncMock(return_value=record),
    )
    return ledger


async def test_the_ledger_is_written_before_the_tracker_is_synchronised():
    calls: list[str] = []
    ledger = SimpleNamespace(
        has_resolution=AsyncMock(side_effect=lambda *_: calls.append("has") or False),
        record_resolution=AsyncMock(side_effect=lambda *_: calls.append("record") or True),
    )
    tracker = SimpleNamespace(
        get_pending_expired=AsyncMock(return_value=[{"signal_id": "sig-1", "details": _details()}]),
        resolve=AsyncMock(side_effect=lambda *_: calls.append("resolve")),
        update_resolution_details=AsyncMock(),
        set_outcome_event=AsyncMock(return_value=True),
    )
    service = _service(ledger, Resolution("target", 110.0, _CREATED_AT, 3), tracker)

    await service.reconcile_pending_signals()

    assert calls == ["has", "record", "resolve"]


async def test_an_existing_resolution_skips_the_write_and_syncs_the_tracker():
    ledger = _ledger(has_resolution=True)
    tracker = SimpleNamespace(
        get_pending_expired=AsyncMock(return_value=[{"signal_id": "sig-1", "details": _details()}]),
        resolve=AsyncMock(),
        update_resolution_details=AsyncMock(),
        set_outcome_event=AsyncMock(return_value=True),
    )
    service = _service(ledger, Resolution("target", 110.0, _CREATED_AT, 3), tracker)

    resolved = await service.reconcile_pending_signals()

    assert resolved == 1
    ledger.record_resolution.assert_not_called()
    tracker.resolve.assert_awaited_once()


async def test_a_ledger_error_keeps_the_signal_pending():
    ledger = SimpleNamespace(
        has_resolution=AsyncMock(return_value=False),
        record_resolution=AsyncMock(side_effect=RuntimeError("disk full")),
    )
    tracker = SimpleNamespace(
        get_pending_expired=AsyncMock(return_value=[{"signal_id": "sig-1", "details": _details()}]),
        resolve=AsyncMock(),
        update_resolution_details=AsyncMock(),
        set_outcome_event=AsyncMock(return_value=True),
    )
    service = _service(ledger, Resolution("target", 110.0, _CREATED_AT, 3), tracker)

    resolved = await service.reconcile_pending_signals()

    assert resolved == 0
    tracker.resolve.assert_not_called()
    tracker.update_resolution_details.assert_not_called()


async def test_a_duplicate_write_keeps_the_signal_pending():
    ledger = _ledger(has_resolution=False, record=False)
    tracker = SimpleNamespace(
        get_pending_expired=AsyncMock(return_value=[{"signal_id": "sig-1", "details": _details()}]),
        resolve=AsyncMock(),
        update_resolution_details=AsyncMock(),
        set_outcome_event=AsyncMock(return_value=True),
    )
    service = _service(ledger, Resolution("target", 110.0, _CREATED_AT, 3), tracker)

    resolved = await service.reconcile_pending_signals()

    assert resolved == 0
    tracker.resolve.assert_not_called()


async def test_a_no_data_resolution_writes_no_boolean_outcome():
    ledger = _ledger()
    tracker = SimpleNamespace(
        get_pending_expired=AsyncMock(return_value=[{"signal_id": "sig-1", "details": _details()}]),
        resolve=AsyncMock(),
        update_resolution_details=AsyncMock(),
        set_outcome_event=AsyncMock(return_value=True),
    )
    service = _service(ledger, Resolution("no_data", None, None, 0), tracker)

    resolved = await service.reconcile_pending_signals()

    assert resolved == 1
    tracker.resolve.assert_not_called()
    tracker.update_resolution_details.assert_awaited_once()
    details = tracker.update_resolution_details.await_args.args[1]
    assert details["resolution_status"] == "no_data"


async def test_the_ledger_is_not_touched_when_the_flag_is_off():
    ledger = _ledger()
    tracker = SimpleNamespace(
        get_pending_expired=AsyncMock(return_value=[{"signal_id": "sig-1", "details": _details()}]),
        resolve=AsyncMock(),
        update_resolution_details=AsyncMock(),
        set_outcome_event=AsyncMock(return_value=True),
    )
    service = _service(ledger, Resolution("target", 110.0, _CREATED_AT, 3), tracker)
    service._performance_ledger_enabled = False

    resolved = await service.reconcile_pending_signals()

    assert resolved == 1
    ledger.has_resolution.assert_not_called()
    ledger.record_resolution.assert_not_called()
    tracker.resolve.assert_awaited_once()


async def test_the_recorded_resolution_carries_the_signal_identity():
    ledger = _ledger()
    service = _service(ledger, Resolution("target", 110.0, _CREATED_AT, 3))

    await service.reconcile_pending_signals()

    record = ledger.record_resolution.await_args.args[0]
    assert record.signal_id == "sig-1"
    assert record.symbol == "BTC/USDT"
    assert record.timeframe == "1h"
    assert record.side == "buy"
    assert record.entry == 100.0
    assert record.stop == 95.0
    assert record.target == 110.0
    assert record.exit_reason == "target"
    assert record.exit_price == 110.0
    assert record.exit_at == _CREATED_AT
    assert record.created_at == _CREATED_AT
    assert record.candles_used == 3
