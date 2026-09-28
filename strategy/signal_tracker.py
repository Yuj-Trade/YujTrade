import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import numpy as np

from common.constants import SIGNAL_EXPIRY_BY_TIMEFRAME


def make_signal_id(
    symbol: str, timeframe: str, timestamp: datetime, signal_type: str
) -> str:
    """Signal ID for Generator <-> Backtest linkage."""
    if isinstance(timestamp, datetime):
        ts = timestamp.isoformat()
    else:
        ts = str(timestamp)
    return f"{symbol}|{timeframe}|{ts}|{signal_type}"


class SignalTracker:
    def __init__(self, storage_path: str = "signal_history.json"):
        self.storage_path = Path(storage_path)
        self.history = self._load_history()
        self._lock = asyncio.Lock()

    def _load_history(self) -> Dict[str, Any]:
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_history_sync(self):
        with open(self.storage_path, "w") as f:
            json.dump(self.history, f, indent=4)

    async def _save_history(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._save_history_sync)

    async def record(self, signal_id: str, outcome: Optional[bool], details: Dict[str, Any]):
        async with self._lock:
            await self._record_locked(signal_id, outcome, details)

    async def _record_locked(self, signal_id: str, outcome: Optional[bool], details: Dict[str, Any]):
        """Write the outcome and persist it. The caller must already hold
        self._lock — asyncio.Lock is not reentrant, so resolve must route
        through this helper instead of calling record under the lock."""
        # شکاف ۳۷: نوشتن فایل با lock سری می‌شود تا record/resolve هم‌زمان
        # رقابت نکنند؛ I/O در executor اجرا می‌شود تا event loop بلاک نشود.
        self.history[signal_id] = {"outcome": outcome, "details": details}
        await self._save_history()

    async def resolve(self, signal_id: str, outcome: bool, details: Dict[str, Any] = None):
        async with self._lock:
            entry = self.history.get(signal_id, {})
            merged = dict(entry.get("details", {}))
            if details:
                merged.update(details)
            await self._record_locked(signal_id, outcome, merged)

    async def get_pending_expired(
        self, now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Snapshot of pending signals whose per-timeframe expiry window has
        passed (SIGNAL_EXPIRY_BY_TIMEFRAME). The lock is taken so the snapshot
        cannot race with concurrent record/resolve calls; callers use it for
        live reconciliation (gap 31)."""
        # شکاف ۳۱: pendingهای منقضی‌شده برای reconciliation دوره‌ای در مسیر
        # Production. ساعت انقضا از SIGNAL_EXPIRY_BY_TIMEFRAME (منبع واحد).
        now = now or datetime.now(timezone.utc)
        async with self._lock:
            expired: List[Dict[str, Any]] = []
            for sid, data in self.history.items():
                if data.get("outcome") is not None:
                    continue
                details = dict(data.get("details", {}))
                parts = sid.split("|")
                symbol = details.get("symbol") or (parts[0] if parts else None)
                timeframe = details.get("timeframe") or (
                    parts[1] if len(parts) > 1 else None
                )
                expiry_hours = SIGNAL_EXPIRY_BY_TIMEFRAME.get(timeframe)
                if not expiry_hours:
                    continue
                created_at = self._extract_created_at(sid, details)
                if created_at is None:
                    continue
                if now - created_at < timedelta(hours=expiry_hours):
                    continue
                expired.append({"signal_id": sid, "details": details})
            return expired

    @staticmethod
    def _extract_created_at(
        signal_id: str, details: Dict[str, Any]
    ) -> Optional[datetime]:
        """Creation time from details, falling back to the timestamp embedded
        in the signal id (third '|'-separated segment). Naive datetimes are
        treated as UTC."""
        raw = details.get("created_at")
        created: Optional[datetime] = None
        if isinstance(raw, datetime):
            created = raw
        elif isinstance(raw, str):
            try:
                created = datetime.fromisoformat(raw)
            except ValueError:
                created = None
        if created is None:
            parts = signal_id.split("|")
            if len(parts) < 3:
                return None
            try:
                created = datetime.fromisoformat(parts[2])
            except ValueError:
                return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created

    def get_performance_summary(self) -> Dict[str, float]:
        resolved = {sid: data for sid, data in self.history.items() if data.get("outcome") is True or data.get("outcome") is False}
        total_signals = len(resolved)
        if total_signals == 0:
            return {"total": 0, "win_rate": 0.0, "pending": len(self.history)}
        wins = sum(1 for data in resolved.values() if data.get("outcome"))
        win_rate = (wins / total_signals) * 100
        return {"total": total_signals, "win_rate": win_rate, "pending": len(self.history) - total_signals}


class AdaptiveThresholdManager:
    def __init__(self):
        self.performance_history: Dict[str, List[Dict]] = {}
        self.min_samples = 50

    def record_performance(self, volatility_regime: str, hurst_range: str, threshold: float, signal_success: bool):
        key = f"{volatility_regime}_{hurst_range}"
        if key not in self.performance_history:
            self.performance_history[key] = []
        self.performance_history[key].append({"threshold": threshold, "success": signal_success, "timestamp": datetime.now(timezone.utc)})
        if len(self.performance_history[key]) > 100:
            self.performance_history[key] = self.performance_history[key][-100:]

    def get_optimal_threshold(self, volatility_regime: str, hurst_range: str, default_threshold: float) -> float:
        key = f"{volatility_regime}_{hurst_range}"
        if key not in self.performance_history or len(self.performance_history[key]) < self.min_samples:
            return default_threshold
        history = self.performance_history[key]
        threshold_performance = {}
        for record in history:
            threshold = round(record["threshold"], 2)
            if threshold not in threshold_performance:
                threshold_performance[threshold] = {"success": 0, "total": 0}
            threshold_performance[threshold]["total"] += 1
            if record["success"]:
                threshold_performance[threshold]["success"] += 1
        best_threshold = default_threshold
        best_accuracy = 0
        for threshold, perf in threshold_performance.items():
            if perf["total"] >= 10:
                accuracy = perf["success"] / perf["total"]
                confidence_interval = 1.96 * np.sqrt((accuracy * (1 - accuracy)) / perf["total"])
                if accuracy - confidence_interval > 0.55:
                    if accuracy > best_accuracy:
                        best_accuracy = accuracy
                        best_threshold = threshold
        return best_threshold


class MLConfidenceCalibrator:
    def __init__(self):
        self.calibration_data: Dict[str, List[Tuple[float, bool, float]]] = {}
        self.calibration_bins = 10

    def add_prediction(self, model_name: str, confidence: float, actual_result: bool, timestamp: datetime = None):
        if model_name not in self.calibration_data:
            self.calibration_data[model_name] = []
        time_decay_factor = 1.0
        if timestamp:
            days_old = (datetime.now(timezone.utc) - timestamp).days
            time_decay_factor = np.exp(-days_old / 90)
        self.calibration_data[model_name].append((confidence, actual_result, time_decay_factor))
        if len(self.calibration_data[model_name]) > 500:
            self.calibration_data[model_name] = self.calibration_data[model_name][-500:]

    def get_calibrated_confidence(self, model_name: str, raw_confidence: float) -> float:
        if model_name not in self.calibration_data or len(self.calibration_data[model_name]) < 20:
            return raw_confidence
        history = self.calibration_data[model_name]
        if raw_confidence >= 100:
            bin_index = self.calibration_bins - 1
        else:
            bin_index = int(raw_confidence * self.calibration_bins / 100)
        bin_predictions = [(conf, result, weight) for conf, result, weight in history if int(conf * self.calibration_bins / 100) == bin_index]
        if not bin_predictions:
            for offset in [-1, 1]:
                adjacent_bin_index = bin_index + offset
                if 0 <= adjacent_bin_index < self.calibration_bins:
                    bin_predictions = [(conf, result, weight) for conf, result, weight in history if int(conf * self.calibration_bins / 100) == adjacent_bin_index]
                    if bin_predictions:
                        break
        if not bin_predictions:
            return raw_confidence
        total_weight = sum(w for _, _, w in bin_predictions)
        correct_weight = sum(w for _, result, w in bin_predictions if result)
        if total_weight == 0:
            return raw_confidence
        accuracy_in_bin = correct_weight / total_weight
        data_points_weight = min(len(bin_predictions) / 50.0, 1.0) * 0.5
        calibrated = raw_confidence * (1 - data_points_weight) + (accuracy_in_bin * 100) * data_points_weight
        return np.clip(calibrated, 0, 100)
