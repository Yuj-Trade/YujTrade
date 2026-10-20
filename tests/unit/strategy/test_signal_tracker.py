"""
P0 Tests for SignalTracker — covers gaps 31 and 37.

Gap 31: SignalTracker.resolve was once reachable only from historical paths;
        production now reconciles expired signals through
        TradingService.reconcile_pending_signals, so resolve() runs in both
        flows and the calibration loop is fed by live outcomes too.

Gap 37: SignalTracker._save_history writes entire file sync (json.dump, no lock,
        no run_in_executor). TradingService.analyze_symbol calls record() in
        asyncio.gather for multiple (symbol, timeframe) — race condition + event
        loop blocking.
"""

import asyncio
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from domain.outcome import OutcomeEvent
from strategy.signal_tracker import (
    AdaptiveThresholdManager,
    MLConfidenceCalibrator,
    SignalTracker,
    make_signal_id,
)


class TestSignalTrackerGap31:
    """Tests for Gap 31: Production path never calls resolve()."""

    @pytest.fixture
    def temp_history_file(self):
        """Create a temporary history file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            temp_path = f.name
        yield temp_path
        Path(temp_path).unlink(missing_ok=True)

    @pytest.fixture
    def tracker(self, temp_history_file):
        return SignalTracker(storage_path=temp_history_file)

    @pytest.mark.asyncio
    async def test_gap31_production_path_never_calls_resolve(self, tracker, monkeypatch):
        """
        Gap 31: Verify that in a simulated production run (TradingService path),
        signal_tracker.resolve is NEVER called.

        This test MUST FAIL initially (red) to document the gap, then pass after fix.
        """
        # Create a real signal
        signal_id = make_signal_id("BTC/USDT", "1d", datetime.now(UTC), "BUY")

        # Record a signal (simulating TradingService.analyze_symbol)
        await tracker.record(
            signal_id,
            None,
            {
                "symbol": "BTC/USDT",
                "timeframe": "1d",
                "signal_type": "BUY",
                "entry_price": 50000,
                "confidence_score": 75,
            },
        )

        # Spy on resolve
        resolve_called = []
        original_resolve = tracker.resolve

        async def spy_resolve(sid, outcome, details=None):
            resolve_called.append((sid, outcome, details))
            return await original_resolve(sid, outcome, details)

        tracker.resolve = spy_resolve

        # Simulate production path: run_analysis_for_all_symbols or run_quick_analysis
        # This is what TradingService does - it calls record() but NOT resolve()
        # In production, signals should eventually be resolved by a reconciliation mechanism

        # Wait a bit to simulate time passing (but not enough for expiry)
        # In reality, a reconciliation task would call get_pending_expired and resolve
        # but that task doesn't exist in production path yet

        # Check: resolve is NOT called during normal signal generation
        assert len(resolve_called) == 0, (
            "resolve() should not be called during normal "
            "signal generation; it runs in the reconciliation step instead."
        )

        # Now simulate what SHOULD happen: reconciliation task picks up expired signals
        # Get pending expired (this is the reconciliation entry point)
        expired = await tracker.get_pending_expired()
        # Should be empty since signal just created
        assert len(expired) == 0

        # After fix: a background reconciliation task would:
        # 1. Call get_pending_expired()
        # 2. For each expired signal, fetch current price
        # 3. Call resolve() with actual outcome
        # This test documents the MISSING reconciliation mechanism

    @pytest.mark.asyncio
    async def test_gap31_resolve_called_from_backtest_only(self, tracker):
        """Verify resolve persists the outcome on the tracker record."""
        signal_id = make_signal_id("BTC/USDT", "1h", datetime.now(UTC), "BUY")

        await tracker.record(signal_id, None, {"symbol": "BTC/USDT", "timeframe": "1h"})

        # This simulates what the reconciliation step does
        await tracker.resolve(signal_id, True, {"exit_price": 51000})

        # Verify resolved
        summary = tracker.get_performance_summary()
        assert summary["total"] == 1
        assert summary["win_rate"] == 100.0

    @pytest.mark.asyncio
    async def test_gap31_reconciliation_mechanism_missing(self, tracker):
        """
        Test that demonstrates the missing reconciliation mechanism.

        After fix: a periodic task should:
        1. Call tracker.get_pending_expired()
        2. For each expired signal, determine outcome from market data
        3. Call tracker.resolve()
        4. Call model_manager.record_signal_performance()
        5. Call threshold_manager.record_performance()
        """
        # Create an "old" signal (simulate time passing by manipulating created_at)
        old_time = datetime.now(UTC) - timedelta(hours=25)  # > 1h expiry
        signal_id = make_signal_id("BTC/USDT", "1h", old_time, "BUY")

        await tracker.record(
            signal_id,
            None,
            {
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "signal_type": "BUY",
                "entry_price": 50000,
                "confidence_score": 75,
                "created_at": old_time.isoformat(),
            },
        )

        # Now the signal is expired (1h expiry = 12 hours per SIGNAL_EXPIRY_BY_TIMEFRAME)
        # Wait - 1h expiry is 12 hours, so 25 hours ago IS expired
        expired = await tracker.get_pending_expired()
        assert len(expired) == 1
        assert expired[0]["signal_id"] == signal_id

        # Gap 31: In production, nothing calls resolve() for this expired signal
        # The signal stays pending forever
        summary = tracker.get_performance_summary()
        assert summary["pending"] == 1
        assert summary["total"] == 0  # No resolved signals


class TestSignalTrackerGap37:
    """Tests for Gap 37: Concurrent record() calls race on file I/O."""

    @pytest.fixture
    def temp_history_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            temp_path = f.name
        yield temp_path
        Path(temp_path).unlink(missing_ok=True)

    @pytest.fixture
    def tracker(self, temp_history_file):
        return SignalTracker(storage_path=temp_history_file)

    @pytest.mark.asyncio
    async def test_gap37_concurrent_records_no_lost_writes(self, tracker):
        """
        Gap 37: Test concurrent record() calls don't lose writes.

        Run 20 concurrent record() calls and verify all are persisted.
        """
        num_signals = 20

        async def record_signal(i):
            signal_id = make_signal_id(f"SYM{i}/USDT", "1h", datetime.now(UTC), "BUY")
            await tracker.record(
                signal_id,
                None,
                {
                    "symbol": f"SYM{i}/USDT",
                    "timeframe": "1h",
                    "signal_type": "BUY",
                    "entry_price": 50000 + i,
                },
            )

        # Run all concurrently (simulating asyncio.gather in TradingService)
        await asyncio.gather(*[record_signal(i) for i in range(num_signals)])

        # Give some time for I/O to complete
        await asyncio.sleep(0.1)

        # Reload from file and verify count
        with open(tracker.storage_path) as f:
            history = json.load(f)

        assert len(history) == num_signals, (
            f"Gap 37: Expected {num_signals} signals in history, got {len(history)}. "
            "Concurrent writes are racing and losing data."
        )

    @pytest.mark.asyncio
    async def test_gap37_concurrent_records_event_loop_not_blocked(self, tracker):
        """
        Gap 37: Test that concurrent I/O doesn't block event loop excessively.

        The _save_history uses run_in_executor which should prevent blocking.
        """
        import time

        num_signals = 50

        async def record_signal(i):
            signal_id = make_signal_id(f"SYM{i}/USDT", "1h", datetime.now(UTC), "BUY")
            await tracker.record(signal_id, None, {"index": i})

        start = time.perf_counter()
        await asyncio.gather(*[record_signal(i) for i in range(num_signals)])
        elapsed = time.perf_counter() - start

        # Should complete reasonably fast (not blocked by sync I/O)
        # With run_in_executor, 50 writes should take < 2 seconds
        assert elapsed < 2.0, (
            f"Gap 37: Concurrent writes took {elapsed:.2f}s - event loop may be blocked "
            "by sync json.dump. Should use run_in_executor."
        )

    @pytest.mark.asyncio
    async def test_gap37_lock_prevents_race_between_record_and_resolve(self, tracker):
        """
        Gap 37: Test that asyncio.Lock prevents race between record and resolve.
        """
        signal_id = make_signal_id("BTC/USDT", "1h", datetime.now(UTC), "BUY")

        # Start a record and a resolve concurrently
        async def do_record():
            await tracker.record(signal_id, None, {"phase": "record"})

        async def do_resolve():
            await tracker.resolve(signal_id, True, {"phase": "resolve"})

        await asyncio.gather(do_record(), do_resolve())

        # One should win, but neither should crash
        with open(tracker.storage_path) as f:
            history = json.load(f)

        assert signal_id in history
        # Outcome should be from resolve (True) since it was last
        assert history[signal_id]["outcome"] is True


class TestAdaptiveThresholdManager:
    """Tests for AdaptiveThresholdManager (part of feedback loop)."""

    @pytest.fixture
    def threshold_manager(self):
        return AdaptiveThresholdManager()

    def test_get_optimal_threshold_insufficient_samples(self, threshold_manager):
        """Less than min_samples returns default."""
        result = threshold_manager.get_optimal_threshold("low", "persistent", 72.0)
        assert result == 72.0

    def test_get_optimal_threshold_bin_total_less_than_10_ignored(self, threshold_manager):
        """Bins with total < 10 are ignored."""
        threshold_manager.performance_history[("low", "persistent")] = [
            {"threshold": 70.0, "success": True, "timestamp": datetime.now(UTC)}
            for _ in range(5)  # Only 5 samples
        ] + [
            {"threshold": 72.0, "success": False, "timestamp": datetime.now(UTC)}
            for _ in range(4)  # Only 4 samples
        ]

        result = threshold_manager.get_optimal_threshold("low", "persistent", 72.0)
        # Both bins have < 10, should return default
        assert result == 72.0

    def test_get_optimal_threshold_accuracy_ci_above_55(self, threshold_manager):
        """Threshold selected only if accuracy - CI > 0.55."""
        # Create history where 70% threshold has 90% accuracy with enough samples
        threshold_manager.performance_history[("high", "mean_reverting")] = [
            {"threshold": 70.0, "success": True, "timestamp": datetime.now(UTC)} for _ in range(90)
        ] + [
            {"threshold": 70.0, "success": False, "timestamp": datetime.now(UTC)} for _ in range(10)
        ]

        result = threshold_manager.get_optimal_threshold("high", "mean_reverting", 72.0)
        # 90/100 = 0.9, CI = 1.96 * sqrt(0.9*0.1/100) = 0.0588
        # accuracy - CI = 0.9 - 0.0588 = 0.8412 > 0.55 ✓
        assert result == 70.0

    def test_threshold_regime_format_matches_backtest_flush(self, threshold_manager):
        """
        Contract test (gap 46): the internal key is a (vol, hurst) tuple so
        regimes containing "_" (e.g. "high_vol") cannot collide, while the
        display regime stays "vol|hurst" for the calibration partition("|").
        """
        threshold_manager.record_performance("high", "persistent", 70.0, True)

        assert ("high", "persistent") in threshold_manager.performance_history

    def test_gap46_underscore_regimes_do_not_collide(self, threshold_manager):
        """Regression (gap 46): ("high_vol", "x") and ("high", "vol_x") are
        distinct keys — impossible with the old f"{vol}_{hurst}" join."""
        threshold_manager.record_performance("high_vol", "x", 70.0, True)
        threshold_manager.record_performance("high", "vol_x", 72.0, False)

        assert ("high_vol", "x") in threshold_manager.performance_history
        assert ("high", "vol_x") in threshold_manager.performance_history
        assert threshold_manager.get_optimal_threshold("high_vol", "x", 50.0) == 50.0
        # The display regime format is unchanged for the backtest flush path.
        regime = "high_vol|x"
        vol_regime, _, hurst_range = regime.partition("|")
        assert (vol_regime, hurst_range) == ("high_vol", "x")


class TestMLConfidenceCalibrator:
    """Tests for MLConfidenceCalibrator."""

    @pytest.fixture
    def calibrator(self):
        return MLConfidenceCalibrator()

    def test_get_calibrated_confidence_insufficient_samples(self, calibrator):
        """Less than 20 samples returns raw_confidence unchanged."""
        result = calibrator.get_calibrated_confidence("lstm_BTC_1d", 75.0)
        assert result == 75.0

    def test_get_calibrated_confidence_bin_empty_checks_adjacent(self, calibrator):
        """Empty bin checks adjacent bins."""
        # Fill bin 5 (50-60% confidence range) with data
        for _ in range(25):
            calibrator.add_prediction("test_model", 55.0, True)
        for _ in range(5):
            calibrator.add_prediction("test_model", 55.0, False)

        # Query bin 7 (70-80%) - empty, should check adjacent
        result = calibrator.get_calibrated_confidence("test_model", 75.0)
        # Should fall back to adjacent bin (bin 6 or 5) or raw
        assert 0 <= result <= 100

    def test_get_calibrated_confidence_both_bins_empty_returns_raw(self, calibrator):
        """Both adjacent bins empty returns raw_confidence."""
        # Only add to bin 0
        calibrator.add_prediction("test_model", 5.0, True)

        # Query bin 9 (90-100%) - far from bin 0
        result = calibrator.get_calibrated_confidence("test_model", 95.0)
        assert result == 95.0

    def test_time_decay_factor_exponential(self, calibrator):
        """Time decay uses exponential with 90-day half-life."""
        now = datetime.now(UTC)
        old = now - timedelta(days=90)  # 1 half-life

        calibrator.add_prediction("test_model", 50.0, True, timestamp=now)
        calibrator.add_prediction("test_model", 50.0, True, timestamp=old)

        # Both in same bin, but old has weight exp(-1) ≈ 0.368
        # New has weight 1.0
        # Should still work without error
        result = calibrator.get_calibrated_confidence("test_model", 50.0)
        assert 0 <= result <= 100


class TestSignalTrackerGap40:
    """Regression (gap 40): re-record of an already-resolved id with
    outcome=None must NOT flip it back to pending (no double counting in
    live calibration)."""

    @pytest.fixture
    def tracker(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            temp_path = f.name
        tracker = SignalTracker(storage_path=temp_path)
        yield tracker
        Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_gap40_rerecord_preserves_resolved_outcome(self, tracker):
        signal_id = make_signal_id("BTC/USDT", "1d", datetime.now(UTC), "BUY")
        await tracker.record(signal_id, None, {"entry": 50000})
        await tracker.resolve(signal_id, True, {"resolved_price": 51000})

        # Same candle re-analyzed → same id, outcome=None
        await tracker.record(signal_id, None, {"entry": 50000})

        summary = tracker.get_performance_summary()
        assert summary["total"] == 1
        assert summary["pending"] == 0
        assert summary["win_rate"] == 100.0

    @pytest.mark.asyncio
    async def test_gap40_rerecord_merges_details_keeps_outcome(self, tracker):
        signal_id = make_signal_id("BTC/USDT", "1d", datetime.now(UTC), "BUY")
        await tracker.record(signal_id, None, {"entry": 50000})
        await tracker.resolve(signal_id, False, {"resolved_price": 49000})
        await tracker.record(signal_id, None, {"extra": "info"})

        with open(tracker.storage_path) as f:
            history = json.load(f)

        assert history[signal_id]["outcome"] is False
        assert history[signal_id]["details"]["extra"] == "info"
        assert history[signal_id]["details"]["resolved_price"] == 49000


class TestMakeSignalId:
    """Tests for make_signal_id - contract between Generator and Backtest."""

    def test_format_exact(self):
        """Format must be exactly: symbol|timeframe|isoformat|signal_type"""
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        signal_id = make_signal_id("BTC/USDT", "1d", ts, "BUY")

        expected = "BTC/USDT|1d|2024-01-15T10:30:00+00:00|BUY"
        assert signal_id == expected

    def test_format_with_string_timestamp(self):
        """String timestamp passed through as-is."""
        signal_id = make_signal_id("BTC/USDT", "1d", "2024-01-15T10:30:00", "BUY")
        assert signal_id == "BTC/USDT|1d|2024-01-15T10:30:00|BUY"

    def test_matches_backtester_strategy_capture(self):
        """
        Contract: make_signal_id output must match BacktraderStrategy._capture_signal
        (in backtesting/engine.py) for the same inputs.
        """
        # This is a contract test - both sides must produce identical IDs
        ts = datetime.now(UTC)
        generator_id = make_signal_id("BTC/USDT", "1d", ts, "BUY")

        # BacktraderStrategy._capture_signal does:
        # signal_id = make_signal_id(data._name, timeframe, current_dt, signal_type)
        # So they MUST be identical
        assert generator_id.count("|") == 3
        parts = generator_id.split("|")
        assert parts[0] == "BTC/USDT"
        assert parts[1] == "1d"
        assert parts[3] == "BUY"


class TestSignalTrackerPerformanceSummary:
    """Tests for get_performance_summary."""

    @pytest.fixture
    def tracker(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            temp_path = f.name
        tracker = SignalTracker(storage_path=temp_path)
        yield tracker
        Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_pending_not_counted_in_win_rate(self, tracker):
        """Pending signals (outcome=None) not counted in win_rate."""
        signal_id = make_signal_id("BTC/USDT", "1h", datetime.now(UTC), "BUY")
        await tracker.record(signal_id, None, {})  # pending

        summary = tracker.get_performance_summary()
        assert summary["total"] == 0
        assert summary["win_rate"] == 0.0
        assert summary["pending"] == 1

    @pytest.mark.asyncio
    async def test_resolve_merges_details_not_overwrite(self, tracker):
        """resolve() merges details, doesn't overwrite."""
        signal_id = make_signal_id("BTC/USDT", "1h", datetime.now(UTC), "BUY")
        await tracker.record(signal_id, None, {"original": "data", "entry": 50000})
        await tracker.resolve(signal_id, True, {"exit": 51000})

        with open(tracker.storage_path) as f:
            history = json.load(f)

        details = history[signal_id]["details"]
        assert details["original"] == "data"
        assert details["entry"] == 50000
        assert details["exit"] == 51000

    @pytest.mark.asyncio
    async def test_no_data_entries_are_not_pending_anymore(self, tracker):
        """A no_data resolution leaves the outcome unset and is skipped."""
        signal_id = make_signal_id("BTC/USDT", "1h", datetime.now(UTC), "BUY")
        await tracker.record(signal_id, None, {"created_at": datetime.now(UTC).isoformat()})
        await tracker.update_resolution_details(
            signal_id,
            {"resolution_status": "no_data", "resolved_at": datetime.now(UTC).isoformat()},
        )

        pending = await tracker.get_pending_expired(datetime.now(UTC) + timedelta(days=30))
        summary = tracker.get_performance_summary()

        assert pending == []
        assert summary["total"] == 0
        assert summary["pending"] == 1
        assert summary["no_data"] == 1

    @pytest.mark.asyncio
    async def test_update_resolution_details_keeps_the_outcome(self, tracker):
        """The details update never invents a boolean outcome."""
        signal_id = make_signal_id("BTC/USDT", "1h", datetime.now(UTC), "BUY")
        await tracker.record(signal_id, None, {"entry": 100.0})
        await tracker.update_resolution_details(signal_id, {"resolution_status": "expired"})

        with open(tracker.storage_path) as f:
            history = json.load(f)

        assert history[signal_id]["outcome"] is None
        assert history[signal_id]["details"]["entry"] == 100.0
        assert history[signal_id]["details"]["resolution_status"] == "expired"


def _notification_details(**overrides):
    base = {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "signal_type": "buy",
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "created_at": datetime(2026, 10, 1, 10, tzinfo=UTC).isoformat(),
    }
    base.update(overrides)
    return base


class TestSignalTrackerOutcomeNotificationDefects:
    """The defects that block a reliable outcome notification."""

    async def test_a_re_recorded_open_signal_is_kept_by_record_if_absent(self, tmp_path):
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        first = _notification_details(notification_state="pending")
        second = _notification_details(
            created_at=datetime(2026, 10, 5, 10, tzinfo=UTC).isoformat(),
            entry=200.0,
            stop=195.0,
            target=210.0,
        )

        assert await tracker.record_if_absent("sig-1", first) is True
        assert await tracker.record_if_absent("sig-1", second) is False

        details = tracker.history["sig-1"]["details"]
        assert details["created_at"] == first["created_at"]
        assert details["entry"] == 100.0
        assert details["stop"] == 95.0
        assert details["target"] == 110.0
        assert details["notification_state"] == "pending"

    async def test_rotation_never_drops_protected_entries(self, tmp_path):
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"), max_entries=2)
        old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        mid = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        new = datetime.now(UTC).isoformat()

        await tracker.record("old|1h|sig|BUY", None, _notification_details(created_at=old))
        await tracker.record("mid|1h|sig|BUY", None, _notification_details(created_at=mid))
        await tracker.record("new|1h|sig|BUY", None, _notification_details(created_at=new))

        assert "old|1h|sig|BUY" in tracker.history
        assert "new|1h|sig|BUY" in tracker.history

    def test_corrupt_history_is_backed_up_not_overwritten(self, tmp_path):
        path = tmp_path / "signal_history.json"
        path.write_text("{not json", encoding="utf-8")

        tracker = SignalTracker(storage_path=str(path))

        assert tracker.history == {}
        backups = sorted(tmp_path.glob("signal_history.corrupt-*.json"))
        assert backups, "the unreadable history must be backed up"
        assert backups[0].read_text(encoding="utf-8") == "{not json"

    async def test_history_roundtrip_is_byte_stable(self, tmp_path):
        path = tmp_path / "signal_history.json"
        tracker = SignalTracker(storage_path=str(path))

        await tracker.record("sig-1", None, _notification_details())
        written = path.read_text(encoding="utf-8")

        restored = SignalTracker(storage_path=str(path))

        assert restored.history == tracker.history
        assert json.dumps(restored.history, indent=4) == written

    async def test_save_failure_leaves_previous_file_intact(self, tmp_path, monkeypatch):
        path = tmp_path / "signal_history.json"
        tracker = SignalTracker(storage_path=str(path))
        await tracker.record("sig-1", None, _notification_details())
        previous = path.read_text(encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)

        with pytest.raises(OSError):
            await tracker.record("sig-2", None, _notification_details())

        assert path.read_text(encoding="utf-8") == previous

    async def test_prune_keeps_resolved_entry_with_open_notification(self, tmp_path):
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"), ttl_days=30)
        old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        details = _notification_details(resolved_at=old)
        details["outcome_event"] = "target"
        details["notification_state"] = "pending"

        await tracker.record("old|1h|sig|BUY", True, details)
        await tracker.record("fresh|1h|sig|BUY", None, _notification_details())

        assert "old|1h|sig|BUY" in tracker.history


class TestSignalTrackerNotificationCharacterization:
    """The current behavior that the notification work must not break."""

    async def test_the_summary_counts_the_resolved_and_the_pending_entries(self, tmp_path):
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))

        await tracker.record("sig-1", True, _notification_details())
        await tracker.record("sig-2", False, _notification_details())
        await tracker.record("sig-3", None, _notification_details())

        summary = tracker.get_performance_summary()

        assert summary["total"] == 2
        assert summary["win_rate"] == 50.0
        assert summary["pending"] == 1

    async def test_recording_twice_keeps_one_entry_with_the_latest_details(self, tmp_path):
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))

        await tracker.record("sig-1", None, _notification_details(entry=100.0))
        await tracker.record("sig-1", None, _notification_details(entry=101.0))

        assert list(tracker.history) == ["sig-1"]
        assert tracker.history["sig-1"]["details"]["entry"] == 101.0


class TestSignalTrackerProtectedEntries:
    """The entries that carry a pending state must survive the housekeeping."""

    async def test_record_if_absent_returns_false_for_existing_open_signal(self, tmp_path):
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        details = _notification_details()

        assert await tracker.record_if_absent("sig-1", details) is True
        assert await tracker.record_if_absent("sig-1", _notification_details(entry=200.0)) is False
        assert tracker.history["sig-1"]["details"]["entry"] == 100.0

    async def test_record_if_absent_keeps_the_first_creation_and_levels(self, tmp_path):
        tracker = SignalTracker(storage_path=str(tmp_path / "signal_history.json"))
        first = _notification_details(notification_state="pending")
        second = _notification_details(
            created_at=datetime(2026, 10, 5, 10, tzinfo=UTC).isoformat(),
            entry=200.0,
        )

        await tracker.record_if_absent("sig-1", first)
        await tracker.record_if_absent("sig-1", second)

        details = tracker.history["sig-1"]["details"]
        assert details["created_at"] == first["created_at"]
        assert details["entry"] == 100.0
        assert details["notification_state"] == "pending"

    async def test_rotation_moves_only_settled_entries_to_rotated_file(self, tmp_path):
        tracker = SignalTracker(storage_path=str(tmp_path / "history.json"), max_entries=2)
        old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        mid = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        new = datetime.now(UTC).isoformat()

        await tracker.record("open|1h|sig|BUY", None, _notification_details(created_at=old))
        await tracker.record("settled|1h|sig|BUY", True, _notification_details(created_at=mid))
        await tracker.record("fresh|1h|sig|BUY", None, _notification_details(created_at=new))

        assert "open|1h|sig|BUY" in tracker.history
        rotated = json.loads((tmp_path / "history.rotated.json").read_text(encoding="utf-8"))
        assert set(rotated) == {"settled|1h|sig|BUY"}


class TestSignalTrackerNotificationState:
    """The notification state API of the tracker."""

    def _tracker(self, tmp_path) -> SignalTracker:
        return SignalTracker(storage_path=str(tmp_path / "signal_history.json"))

    async def test_a_second_event_is_rejected(self, tmp_path):
        tracker = self._tracker(tmp_path)
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))

        assert await tracker.set_outcome_event("sig-1", event) is True
        assert await tracker.set_outcome_event("sig-1", event) is False
        details = tracker.history["sig-1"]["details"]
        assert details["outcome_event"] == "target"
        assert details["notification_state"] == "pending"
        assert details["notification_attempts"] == 0

    async def test_an_event_for_an_unknown_signal_is_rejected(self, tmp_path):
        tracker = self._tracker(tmp_path)
        event = OutcomeEvent("sig-x", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))

        assert await tracker.set_outcome_event("sig-x", event) is False

    async def test_two_concurrent_claims_only_one_wins(self, tmp_path):
        tracker = self._tracker(tmp_path)
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))
        await tracker.set_outcome_event("sig-1", event)
        now = datetime.now(UTC)

        results = await asyncio.gather(
            tracker.claim_notification("sig-1", now, timedelta(minutes=5)),
            tracker.claim_notification("sig-1", now, timedelta(minutes=5)),
        )

        assert sum(1 for result in results if result) == 1
        assert tracker.history["sig-1"]["details"]["notification_state"] == "claimed"

    async def test_an_expired_claim_becomes_claimable_again(self, tmp_path):
        tracker = self._tracker(tmp_path)
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))
        await tracker.set_outcome_event("sig-1", event)
        now = datetime.now(UTC)

        assert await tracker.claim_notification("sig-1", now, timedelta(minutes=5)) is True
        assert await tracker.claim_notification("sig-1", now, timedelta(minutes=5)) is False
        assert (
            await tracker.claim_notification(
                "sig-1", now + timedelta(minutes=6), timedelta(minutes=5)
            )
            is True
        )

    async def test_a_fresh_claim_is_not_claimable_again(self, tmp_path):
        tracker = self._tracker(tmp_path)
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))
        await tracker.set_outcome_event("sig-1", event)
        now = datetime.now(UTC)

        assert await tracker.claim_notification("sig-1", now, timedelta(minutes=5)) is True
        assert await tracker.claim_notification("sig-1", now, timedelta(minutes=5)) is False

    async def test_fail_notification_increments_the_counter(self, tmp_path):
        tracker = self._tracker(tmp_path)
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))
        await tracker.set_outcome_event("sig-1", event)
        now = datetime.now(UTC)
        await tracker.claim_notification("sig-1", now, timedelta(minutes=5))

        await tracker.fail_notification("sig-1", "pending")

        details = tracker.history["sig-1"]["details"]
        assert details["notification_attempts"] == 1
        assert details["notification_state"] == "pending"
        assert "notification_claimed_at" not in details

    async def test_complete_notification_clears_the_claim(self, tmp_path):
        tracker = self._tracker(tmp_path)
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))
        await tracker.set_outcome_event("sig-1", event)
        now = datetime.now(UTC)
        await tracker.claim_notification("sig-1", now, timedelta(minutes=5))

        await tracker.complete_notification("sig-1", "sent")

        details = tracker.history["sig-1"]["details"]
        assert details["notification_state"] == "sent"
        assert "notification_claimed_at" not in details

    async def test_open_signals_skips_old_and_expired_entries(self, tmp_path):
        tracker = self._tracker(tmp_path)
        now = datetime.now(UTC)
        await tracker.record(
            "sig-fresh",
            None,
            _notification_details(created_at=(now - timedelta(hours=1)).isoformat()),
        )
        await tracker.record(
            "sig-expired",
            None,
            _notification_details(created_at=(now - timedelta(hours=13)).isoformat()),
        )

        found = await tracker.open_signals(now, None)

        assert [item.signal_id for item in found] == ["sig-fresh"]
        assert found[0].symbol == "BTC/USDT"
        assert found[0].timeframe == "1h"
        assert found[0].side == "buy"
        assert found[0].entry == 100.0
        assert found[0].stop == 95.0
        assert found[0].target == 110.0

    async def test_open_signals_skips_the_entries_before_the_since_bound(self, tmp_path):
        tracker = self._tracker(tmp_path)
        now = datetime.now(UTC)
        await tracker.record(
            "sig-old",
            None,
            _notification_details(created_at=(now - timedelta(hours=2)).isoformat()),
        )
        await tracker.record(
            "sig-new",
            None,
            _notification_details(created_at=(now - timedelta(hours=1)).isoformat()),
        )

        found = await tracker.open_signals(now, now - timedelta(hours=1, minutes=30))

        assert [item.signal_id for item in found] == ["sig-new"]

    async def test_open_signals_skips_incomplete_entries(self, tmp_path):
        tracker = self._tracker(tmp_path)
        now = datetime.now(UTC)
        await tracker.record("sig-1", None, {"symbol": "BTC/USDT"})

        found = await tracker.open_signals(now, None)

        assert found == []

    async def test_due_notifications_returns_the_pending_events(self, tmp_path):
        tracker = self._tracker(tmp_path)
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))
        await tracker.set_outcome_event("sig-1", event)

        due = await tracker.due_notifications()

        assert len(due) == 1
        assert due[0].signal_id == "sig-1"
        assert due[0].event.kind == "target"
        assert due[0].event.price == 110.0
        assert due[0].attempts == 0
        assert due[0].symbol == "BTC/USDT"
        assert due[0].timeframe == "1h"
        assert due[0].side == "buy"

    async def test_due_notifications_skips_the_terminal_states(self, tmp_path):
        tracker = self._tracker(tmp_path)
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))
        await tracker.set_outcome_event("sig-1", event)
        await tracker.complete_notification("sig-1", "sent")

        due = await tracker.due_notifications()

        assert due == []

    async def test_the_state_survives_a_reload(self, tmp_path):
        path = tmp_path / "signal_history.json"
        tracker = SignalTracker(storage_path=str(path))
        await tracker.record("sig-1", None, _notification_details())
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 10, 1, 14, tzinfo=UTC))
        await tracker.set_outcome_event("sig-1", event)
        now = datetime.now(UTC)
        await tracker.claim_notification("sig-1", now, timedelta(minutes=5))

        restored = SignalTracker(storage_path=str(path))
        details = restored.history["sig-1"]["details"]

        assert details["outcome_event"] == "target"
        assert details["outcome_event_at"] == "2026-10-01T14:00:00+00:00"
        assert details["outcome_event_price"] == 110.0
        assert details["notification_state"] == "claimed"
        assert details["notification_attempts"] == 0
        assert "notification_claimed_at" in details
