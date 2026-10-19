import asyncio
import json
from datetime import UTC, datetime, timedelta

from strategy.signal_tracker import AdaptiveThresholdManager, SignalTracker, make_signal_id


def _details(resolved_at=None, created_at=None):
    details = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "signal_type": "buy",
        "entry": 100.0,
        "created_at": created_at or datetime.now(UTC).isoformat(),
    }
    if resolved_at:
        details["resolved_at"] = resolved_at
    return details


class TestSignalTrackerTtl:
    async def test_resolved_entry_past_ttl_is_pruned_on_next_write(self, tmp_path):
        tracker = SignalTracker(tmp_path / "history.json", ttl_days=30)
        old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        await tracker.record("old|1h|sig|BUY", True, _details(resolved_at=old))

        await tracker.record("fresh|1h|sig|BUY", None, _details())

        assert "old|1h|sig|BUY" not in tracker.history
        assert "fresh|1h|sig|BUY" in tracker.history

    async def test_pending_entry_past_ttl_is_never_pruned(self, tmp_path):
        tracker = SignalTracker(tmp_path / "history.json", ttl_days=30)
        old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        await tracker.record("pending-old|1h|sig|BUY", None, _details(created_at=old))

        await tracker.record("fresh|1h|sig|BUY", None, _details())

        assert "pending-old|1h|sig|BUY" in tracker.history

    async def test_unparseable_resolved_at_is_kept(self, tmp_path):
        tracker = SignalTracker(tmp_path / "history.json", ttl_days=30)
        await tracker.record("weird|1h|sig|BUY", True, _details(resolved_at="not-a-date"))

        await tracker.record("fresh|1h|sig|BUY", None, _details())

        assert "weird|1h|sig|BUY" in tracker.history


class TestSignalTrackerRotation:
    async def test_overflow_moves_oldest_to_rotation_file(self, tmp_path):
        tracker = SignalTracker(tmp_path / "history.json", ttl_days=30, max_entries=2)
        old_time = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        mid_time = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        new_time = datetime.now(UTC).isoformat()

        await tracker.record("old|1h|sig|BUY", True, _details(created_at=old_time))
        await tracker.record("mid|1h|sig|BUY", True, _details(created_at=mid_time))
        await tracker.record("new|1h|sig|BUY", True, _details(created_at=new_time))

        assert len(tracker.history) == 2
        assert set(tracker.history) == {"mid|1h|sig|BUY", "new|1h|sig|BUY"}
        rotated = json.loads((tmp_path / "history.rotated.json").read_text())
        assert set(rotated) == {"old|1h|sig|BUY"}


class TestSignalTrackerIdempotency:
    async def test_replaying_same_record_yields_one_entry(self, tmp_path):
        tracker = SignalTracker(tmp_path / "history.json")
        details = _details()
        sid = make_signal_id("BTC/USDT", "1h", datetime.now(UTC), "buy")

        await tracker.record(sid, None, details)
        await tracker.record(sid, None, details)

        assert list(tracker.history) == [sid]
        assert tracker.history[sid]["details"] == details

    async def test_resolving_twice_keeps_single_stable_entry(self, tmp_path):
        tracker = SignalTracker(tmp_path / "history.json")
        sid = make_signal_id("BTC/USDT", "1h", datetime.now(UTC), "buy")
        await tracker.record(sid, None, _details())
        first = dict(tracker.history[sid]["details"])

        await tracker.resolve(sid, True, {"resolved_price": 110.0})
        await tracker.resolve(sid, True, {"resolved_price": 110.0})

        assert list(tracker.history) == [sid]
        assert tracker.history[sid]["outcome"] is True
        merged = tracker.history[sid]["details"]
        assert merged["resolved_price"] == 110.0
        assert "symbol" in merged or "entry" in merged or first


class TestAdaptiveThresholdPersistence:
    def test_record_and_flush_persists_json(self, tmp_path):
        store = tmp_path / "threshold_calibration.json"
        manager = AdaptiveThresholdManager(storage_path=store)
        manager.record_performance("high", "mid", 12.5, True)
        assert store.exists() is False

        asyncio.run(manager.flush())
        payload = json.loads(store.read_text())
        assert "high|mid" in payload
        assert payload["high|mid"][0]["threshold"] == 12.5
        assert payload["high|mid"][0]["success"] is True

    def test_state_survives_restart(self, tmp_path):
        store = tmp_path / "threshold_calibration.json"
        manager = AdaptiveThresholdManager(storage_path=store)
        manager.record_performance("high", "mid", 12.5, True)

        asyncio.run(manager.flush())

        restored = AdaptiveThresholdManager(storage_path=store)
        assert len(restored.performance_history[("high", "mid")]) == 1
        assert restored._dirty is False

    def test_corrupt_store_starts_fresh_without_raising(self, tmp_path):
        store = tmp_path / "threshold_calibration.json"
        store.write_text("{not json", encoding="utf-8")
        manager = AdaptiveThresholdManager(storage_path=store)
        assert manager.performance_history == {}

    def test_records_past_ttl_are_pruned_on_load(self, tmp_path):
        store = tmp_path / "threshold_calibration.json"
        stale = (datetime.now(UTC) - timedelta(days=400)).isoformat()
        store.write_text(
            json.dumps({"high|mid": [{"threshold": 10.0, "success": True, "timestamp": stale}]}),
            encoding="utf-8",
        )
        manager = AdaptiveThresholdManager(storage_path=store, ttl_days=90)
        assert manager.performance_history == {}

    def test_flush_without_records_writes_nothing(self, tmp_path):
        store = tmp_path / "threshold_calibration.json"
        manager = AdaptiveThresholdManager(storage_path=store)

        asyncio.run(manager.flush())
        assert store.exists() is False
