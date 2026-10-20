import asyncio
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from common.constants import SIGNAL_EXPIRY_BY_TIMEFRAME
from config.logger import logger
from domain.signal_id import make_signal_id as _make_signal_id

TERMINAL_NOTIFICATION_STATES = frozenset({"sent", "shadowed", "suppressed", "abandoned"})


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _is_protected(data: Mapping[str, Any]) -> bool:
    if data.get("outcome") is None:
        return True
    details = data.get("details") or {}
    return (
        "outcome_event" in details
        and details.get("notification_state") not in TERMINAL_NOTIFICATION_STATES
    )


def make_signal_id(symbol: str, timeframe: str, timestamp: datetime, signal_type: str) -> str:
    return _make_signal_id(symbol, timeframe, timestamp, signal_type)


class SignalTracker:
    def __init__(
        self,
        storage_path: str = "signal_history.json",
        ttl_days: int = 30,
        max_entries: int = 5000,
    ):
        self.storage_path = Path(storage_path)
        self.ttl_days = int(ttl_days)
        self.max_entries = int(max_entries)
        self.history = self._load_history()
        self._lock = asyncio.Lock()

    @property
    def rotation_path(self) -> Path:
        return self.storage_path.with_suffix(".rotated.json")

    def _load_history(self) -> dict[str, Any]:
        if not self.storage_path.exists():
            return {}
        try:
            with open(self.storage_path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            self._backup_corrupt_history(exc)
            return {}
        if not isinstance(payload, dict):
            self._backup_corrupt_history(TypeError("the history root must be a mapping"))
            return {}
        return payload

    def _backup_corrupt_history(self, exc: Exception) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.storage_path.with_name(
            f"{self.storage_path.stem}.corrupt-{stamp}{self.storage_path.suffix}"
        )
        try:
            os.replace(self.storage_path, backup)
        except OSError as move_error:
            logger.error(
                f"Signal history {self.storage_path} is unreadable ({exc}) and the backup "
                f"failed: {move_error}"
            )
            return
        logger.error(
            f"Signal history {self.storage_path} was unreadable ({exc}); it was moved to {backup}"
        )

    async def _save_history(self):
        payload = json.dumps(self.history, indent=4)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, write_text_atomic, self.storage_path, payload)

    async def record(self, signal_id: str, outcome: bool | None, details: dict[str, Any]):
        async with self._lock:
            await self._record_locked(signal_id, outcome, details)

    async def record_if_absent(self, signal_id: str, details: dict[str, Any]) -> bool:
        async with self._lock:
            if signal_id in self.history:
                return False
            self.history[signal_id] = {"outcome": None, "details": details}
            self._prune_expired()
            self._rotate_if_needed()
            await self._save_history()
            return True

    async def _record_locked(self, signal_id: str, outcome: bool | None, details: dict[str, Any]):
        existing = self.history.get(signal_id)
        if existing is not None and existing.get("outcome") is not None and outcome is None:
            merged_details = dict(existing.get("details", {}))
            merged_details.update(details)
            self.history[signal_id] = {
                "outcome": existing["outcome"],
                "details": merged_details,
            }
        else:
            self.history[signal_id] = {"outcome": outcome, "details": details}
        self._prune_expired()
        self._rotate_if_needed()
        await self._save_history()

    def _entry_age_cutoff(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=self.ttl_days)

    def _prune_expired(self) -> None:
        cutoff = self._entry_age_cutoff()
        expired_ids = []
        for sid, data in self.history.items():
            if _is_protected(data):
                continue
            details = data.get("details", {})
            raw = details.get("resolved_at") or details.get("created_at")
            resolved_at = None
            if isinstance(raw, str):
                try:
                    resolved_at = datetime.fromisoformat(raw)
                except ValueError:
                    resolved_at = None
            if resolved_at is None:
                continue
            if resolved_at.tzinfo is None:
                resolved_at = resolved_at.replace(tzinfo=UTC)
            if resolved_at < cutoff:
                expired_ids.append(sid)
        for sid in expired_ids:
            del self.history[sid]

    def _rotate_if_needed(self) -> None:
        overflow = len(self.history) - self.max_entries
        if overflow <= 0:
            return
        candidates = [(sid, data) for sid, data in self.history.items() if not _is_protected(data)]
        candidates.sort(
            key=lambda item: (
                SignalTracker._extract_created_at(item[0], item[1].get("details", {}))
                or datetime.min.replace(tzinfo=UTC)
            ),
        )
        movable = candidates[:overflow]
        if len(movable) < overflow:
            protected = len(self.history) - len(movable)
            logger.warning(
                f"Signal history rotation kept {protected} protected entries, "
                f"{len(self.history)} entries exceed the limit of {self.max_entries}."
            )
        rotated_out = dict(movable)
        for sid in rotated_out:
            del self.history[sid]
        existing_rotated = {}
        if self.rotation_path.exists():
            try:
                with open(self.rotation_path, encoding="utf-8") as f:
                    existing_rotated = json.load(f)
            except (OSError, json.JSONDecodeError):
                existing_rotated = {}
        existing_rotated.update(rotated_out)
        write_text_atomic(self.rotation_path, json.dumps(existing_rotated, indent=4))

    async def resolve(self, signal_id: str, outcome: bool, details: dict[str, Any] = None):
        async with self._lock:
            entry = self.history.get(signal_id, {})
            merged = dict(entry.get("details", {}))
            if details:
                merged.update(details)
            await self._record_locked(signal_id, outcome, merged)

    async def update_resolution_details(self, signal_id: str, details: dict[str, Any]):
        async with self._lock:
            entry = self.history.get(signal_id, {})
            merged = dict(entry.get("details", {}))
            merged.update(details)
            await self._record_locked(signal_id, entry.get("outcome"), merged)

    async def get_pending_expired(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(UTC)
        async with self._lock:
            expired: list[dict[str, Any]] = []
            for sid, data in self.history.items():
                if data.get("outcome") is not None:
                    continue
                details = dict(data.get("details", {}))
                if details.get("resolution_status") == "no_data":
                    continue
                parts = sid.split("|")
                timeframe = details.get("timeframe") or (parts[1] if len(parts) > 1 else None)
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
    def _extract_created_at(signal_id: str, details: dict[str, Any]) -> datetime | None:
        raw = details.get("created_at")
        created: datetime | None = None
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
            created = created.replace(tzinfo=UTC)
        return created

    def get_performance_summary(self) -> dict[str, float]:
        resolved = {
            sid: data
            for sid, data in self.history.items()
            if data.get("outcome") is True or data.get("outcome") is False
        }
        no_data = sum(
            1
            for data in self.history.values()
            if (data.get("details") or {}).get("resolution_status") == "no_data"
        )
        total_signals = len(resolved)
        if total_signals == 0:
            return {
                "total": 0,
                "win_rate": 0.0,
                "pending": len(self.history),
                "no_data": no_data,
            }
        wins = sum(1 for data in resolved.values() if data.get("outcome"))
        win_rate = (wins / total_signals) * 100
        return {
            "total": total_signals,
            "win_rate": win_rate,
            "pending": len(self.history) - total_signals,
            "no_data": no_data,
        }


class AdaptiveThresholdManager:
    def __init__(
        self,
        storage_path: str = "threshold_calibration.json",
        ttl_days: int = 90,
        max_samples_per_key: int = 100,
    ):
        self.storage_path = Path(storage_path)
        self.ttl_days = int(ttl_days)
        self.max_samples_per_key = int(max_samples_per_key)
        self.performance_history: dict[tuple, list[dict]] = {}
        self.min_samples = 50
        self._dirty = False
        self._load()

    @staticmethod
    def _key(volatility_regime: str, hurst_range: str) -> tuple:
        return (str(volatility_regime), str(hurst_range))

    @staticmethod
    def _serialize_key(key: tuple) -> str:
        return f"{key[0]}|{key[1]}"

    @staticmethod
    def _deserialize_key(raw: str) -> tuple:
        vol_regime, _, hurst_range = str(raw).partition("|")
        return (vol_regime, hurst_range)

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path) as f:
                payload = json.load(f)
            for raw_key, records in payload.items():
                key = self._deserialize_key(raw_key)
                loaded = []
                for record in records:
                    raw_timestamp = record.get("timestamp")
                    timestamp = None
                    if isinstance(raw_timestamp, str):
                        try:
                            timestamp = datetime.fromisoformat(raw_timestamp)
                        except ValueError:
                            timestamp = None
                    loaded.append(
                        {
                            "threshold": float(record.get("threshold", 0.0)),
                            "success": bool(record.get("success", False)),
                            "timestamp": timestamp or datetime.now(UTC),
                        }
                    )
                self.performance_history[key] = loaded
            self._prune_expired()
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Threshold calibration store unreadable, starting fresh: {e}")
            self.performance_history = {}

    def _prune_expired(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=self.ttl_days)
        for key in list(self.performance_history):
            kept = [
                record for record in self.performance_history[key] if record["timestamp"] >= cutoff
            ]
            if kept:
                self.performance_history[key] = kept
            else:
                del self.performance_history[key]

    def record_performance(
        self, volatility_regime: str, hurst_range: str, threshold: float, signal_success: bool
    ):
        key = self._key(volatility_regime, hurst_range)
        if key not in self.performance_history:
            self.performance_history[key] = []
        self.performance_history[key].append(
            {
                "threshold": threshold,
                "success": signal_success,
                "timestamp": datetime.now(UTC),
            }
        )
        if len(self.performance_history[key]) > self.max_samples_per_key:
            trimmed = self.performance_history[key][-self.max_samples_per_key :]
            self.performance_history[key] = trimmed
        self._dirty = True

    def _flush_sync(self) -> None:
        self._prune_expired()
        payload = {
            self._serialize_key(key): [
                {
                    "threshold": record["threshold"],
                    "success": record["success"],
                    "timestamp": record["timestamp"].isoformat(),
                }
                for record in records
            ]
            for key, records in self.performance_history.items()
        }
        with open(self.storage_path, "w") as f:
            json.dump(payload, f, indent=4)

    async def flush(self) -> None:
        if not self._dirty:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._flush_sync)
        self._dirty = False

    def get_optimal_threshold(
        self, volatility_regime: str, hurst_range: str, default_threshold: float
    ) -> float:
        key = self._key(volatility_regime, hurst_range)
        if (
            key not in self.performance_history
            or len(self.performance_history[key]) < self.min_samples
        ):
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
        self.calibration_data: dict[str, list[tuple[float, bool, float]]] = {}
        self.calibration_bins = 10

    def add_prediction(
        self, model_name: str, confidence: float, actual_result: bool, timestamp: datetime = None
    ):
        if model_name not in self.calibration_data:
            self.calibration_data[model_name] = []
        time_decay_factor = 1.0
        if timestamp:
            days_old = (datetime.now(UTC) - timestamp).days
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
        bin_predictions = [
            (conf, result, weight)
            for conf, result, weight in history
            if int(conf * self.calibration_bins / 100) == bin_index
        ]
        if not bin_predictions:
            for offset in [-1, 1]:
                adjacent_bin_index = bin_index + offset
                if 0 <= adjacent_bin_index < self.calibration_bins:
                    bin_predictions = [
                        (conf, result, weight)
                        for conf, result, weight in history
                        if int(conf * self.calibration_bins / 100) == adjacent_bin_index
                    ]
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
        calibrated = (
            raw_confidence * (1 - data_points_weight) + (accuracy_in_bin * 100) * data_points_weight
        )
        return np.clip(calibrated, 0, 100)
