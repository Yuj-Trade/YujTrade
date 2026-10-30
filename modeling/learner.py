import asyncio
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from application.learning_alerts import LearningEvent
from config.logger import logger
from modeling.drift import (
    DEFAULT_DRIFT_FEATURES,
    build_drift_features,
    detect_feature_drift,
    drift_summary,
    split_windows,
)
from modeling.promotion import PromotionPolicy, evaluate_promotion

DEFAULT_MODEL_TYPES = ("xgboost",)


@dataclass(frozen=True)
class LearningSettings:
    enabled: bool = False
    model_types: tuple[str, ...] = DEFAULT_MODEL_TYPES
    min_interval_minutes: int = 360
    min_new_candles: int = 50
    max_concurrency: int = 1
    promote: bool = True
    drift_gate: bool = False
    max_interval_multiplier: int = 8
    live_window: int = 300
    training_source: str = "ohlcv"
    alert_drift_cooldown_hours: float = 24.0

    @classmethod
    def from_config(cls, config_manager: Any) -> "LearningSettings":
        raw = config_manager.get("model_learning", {}) or {}
        model_types = tuple(raw.get("model_types", DEFAULT_MODEL_TYPES))
        return cls(
            enabled=bool(raw.get("enabled", False)),
            model_types=model_types or DEFAULT_MODEL_TYPES,
            min_interval_minutes=max(1, int(raw.get("min_interval_minutes", 360))),
            min_new_candles=max(0, int(raw.get("min_new_candles", 50))),
            max_concurrency=max(1, int(raw.get("max_concurrency", 1))),
            promote=bool(raw.get("promote", True)),
            drift_gate=bool(raw.get("drift_gate", False)),
            max_interval_multiplier=max(1, int(raw.get("max_interval_multiplier", 8))),
            live_window=max(20, int(raw.get("live_window", 300))),
            training_source=str(raw.get("training_source", "ohlcv")),
            alert_drift_cooldown_hours=max(0.0, float(raw.get("alert_drift_cooldown_hours", 24))),
        )


@dataclass
class LearningOutcome:
    key: str
    status: str
    version: str = ""
    reasons: tuple[str, ...] = ()


class ModelLearner:
    def __init__(
        self,
        model_manager: Any,
        data_provider: Any,
        config_manager: Any,
        clock=time.monotonic,
    ) -> None:
        self.model_manager = model_manager
        self.data_provider = data_provider
        self.config_manager = config_manager
        self.settings = LearningSettings.from_config(config_manager)
        self.policy = PromotionPolicy.from_config(config_manager)
        self._clock = clock
        self._inflight: set[str] = set()
        self._last_attempt: dict[str, float] = {}
        self._last_rows: dict[str, int] = {}
        self._rejections: dict[str, int] = {}
        self._tasks: set[asyncio.Task] = set()
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrency)
        self.outcomes: dict[str, LearningOutcome] = {}
        self.alert_sink: Any | None = None
        self.feature_store: Any | None = None
        self._drift_alert_at: dict[str, float] = {}

    @staticmethod
    def key_for(model_type: str, symbol: str, timeframe: str) -> str:
        return f"{model_type}-{symbol}-{timeframe}"

    def interval_seconds(self, key: str) -> float:
        base = self.settings.min_interval_minutes * 60.0
        rejections = min(self._rejections.get(key, 0), self.settings.max_interval_multiplier)
        return base * (2**rejections)

    def is_due(self, key: str) -> bool:
        last = self._last_attempt.get(key)
        if last is None:
            return True
        return (self._clock() - last) >= self.interval_seconds(key)

    def request(self, symbol: str, timeframe: str) -> list[str]:
        if not self.settings.enabled:
            return []

        scheduled: list[str] = []
        for model_type in self.settings.model_types:
            key = self.key_for(model_type, symbol, timeframe)
            if key in self._inflight or not self.is_due(key):
                continue
            self._inflight.add(key)
            task = asyncio.create_task(self._learn(key, model_type, symbol, timeframe))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            scheduled.append(key)
        return scheduled

    async def _learn(self, key: str, model_type: str, symbol: str, timeframe: str) -> None:
        async with self._semaphore:
            try:
                await self._run_job(key, model_type, symbol, timeframe)
            except Exception as exc:
                self._last_attempt[key] = self._clock()
                self.outcomes[key] = LearningOutcome(key=key, status="failed")
                logger.opt(exception=True).warning(f"Continuous learning failed for {key}: {exc}")
            finally:
                self._inflight.discard(key)

    async def _run_job(self, key: str, model_type: str, symbol: str, timeframe: str) -> None:
        data = await self.data_provider.get_data_for_model(symbol, timeframe)
        if data is None or data.empty:
            return

        previous_rows = self._last_rows.get(key)
        if previous_rows is not None and len(data) - previous_rows < self.settings.min_new_candles:
            logger.debug(
                f"Learning skipped for {key}: {len(data) - previous_rows} new candles "
                f"< {self.settings.min_new_candles}"
            )
            return

        self._last_attempt[key] = self._clock()

        drift = self._drift_report(data, timeframe)
        if drift["drifted"] and not self._drift_within_cooldown(key):
            self._drift_alert_at[key] = self._clock()
            await self._emit(
                LearningEvent(
                    "drift_detected",
                    key,
                    model_type,
                    symbol,
                    timeframe,
                    "",
                    tuple(drift["features"]),
                )
            )
        if self.settings.drift_gate and not drift["drifted"]:
            self._last_rows[key] = len(data)
            self.outcomes[key] = LearningOutcome(key=key, status="no_drift")
            logger.debug(f"Learning skipped for {key}: no feature drift")
            return

        baseline = self._baseline_metrics(model_type, symbol, timeframe)
        feature_frame = await self._store_training_frame(model_type, symbol, timeframe)
        outcome = await self.model_manager.train_model(
            model_type,
            symbol,
            timeframe,
            data,
            promote=False,
            warm_start=True,
            feature_frame=feature_frame,
        )
        if outcome is None:
            self.outcomes[key] = LearningOutcome(key=key, status="failed")
            await self._emit(LearningEvent("failed", key, model_type, symbol, timeframe, "", ()))
            return

        self._last_rows[key] = len(data)

        decision = evaluate_promotion(baseline, outcome.oos_metrics, self.policy)
        if not self.settings.promote or not decision.promote:
            self._rejections[key] = self._rejections.get(key, 0) + 1
            self.outcomes[key] = LearningOutcome(
                key=key, status="rejected", version=outcome.version, reasons=decision.reasons
            )
            logger.warning(
                f"Rejected learned {model_type} version {outcome.version} "
                f"for {symbol}-{timeframe}; reasons={decision.reasons}"
            )
            await self._emit(
                LearningEvent(
                    "rejected",
                    key,
                    model_type,
                    symbol,
                    timeframe,
                    outcome.version,
                    tuple(decision.reasons),
                )
            )
            return

        try:
            self.model_manager.artifacts.promote_version(
                model_type, symbol, timeframe, outcome.version
            )
        except (OSError, ValueError) as exc:
            self.outcomes[key] = LearningOutcome(
                key=key, status="promotion_failed", version=outcome.version
            )
            logger.error(f"Promotion of learned {key} version {outcome.version} failed: {exc}")
            await self._emit(
                LearningEvent(
                    "promotion_failed",
                    key,
                    model_type,
                    symbol,
                    timeframe,
                    outcome.version,
                    (str(exc),),
                )
            )
            return

        self._rejections[key] = 0
        self.outcomes[key] = LearningOutcome(
            key=key, status="promoted", version=outcome.version, reasons=decision.reasons
        )
        logger.info(
            f"Promoted learned {model_type} version {outcome.version} for {symbol}-{timeframe}"
        )
        await self._emit(
            LearningEvent(
                "promoted",
                key,
                model_type,
                symbol,
                timeframe,
                outcome.version,
                tuple(decision.reasons),
            )
        )

    def _baseline_metrics(self, model_type: str, symbol: str, timeframe: str) -> dict[str, float]:
        try:
            metadata = self.model_manager.artifacts.read_metadata(model_type, symbol, timeframe)
        except (OSError, ValueError):
            return {}
        metrics = metadata.get("oos_metrics") if isinstance(metadata, dict) else None
        return metrics if isinstance(metrics, dict) else {}

    def _drift_report(self, data: pd.DataFrame, timeframe: str) -> dict:
        reference, live = split_windows(data, self.settings.live_window)
        if reference.empty or live.empty:
            return {"drifted": False, "features": []}
        reports = detect_feature_drift(
            build_drift_features(reference),
            build_drift_features(live),
            features=DEFAULT_DRIFT_FEATURES,
            alpha=float(self.config_manager.get("drift_alpha", 0.05)),
            min_window=int(self.config_manager.get("drift_min_window", 100)),
        )
        summary = drift_summary(
            reports,
            float(self.config_manager.get("drift_alpha", 0.05)),
            int(self.config_manager.get("drift_min_window", 100)),
        )
        return {
            "drifted": bool(summary.get("drifted")),
            "features": list(summary.get("drifted_features") or []),
        }

    @property
    def pending(self) -> int:
        return len(self._inflight)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await self.drain()
        self._tasks.clear()
        self._inflight.clear()

    async def _store_training_frame(
        self, model_type: str, symbol: str, timeframe: str
    ) -> Any | None:
        store = self.feature_store
        if store is None or self.settings.training_source != "feature_store":
            return None
        try:
            metadata = self.model_manager.artifacts.read_metadata(model_type, symbol, timeframe)
        except (OSError, ValueError):
            metadata = None
        feature_list = metadata.get("feature_list") if isinstance(metadata, dict) else None
        if not feature_list:
            logger.info("Feature-store training unavailable: no artifact feature list.")
            return None
        try:
            count = await store.count_labeled(symbol, timeframe, feature_list)
        except Exception as exc:
            logger.warning(f"Feature-store row count failed for {symbol}-{timeframe}: {exc}")
            return None
        minimum = int(self.config_manager.get("feature_store_min_rows", 500))
        if count < minimum:
            logger.info(
                f"Feature-store training skipped for {symbol}-{timeframe}: "
                f"{count} labeled rows < {minimum}."
            )
            return None
        frame = await store.training_frame(
            symbol, timeframe, feature_list, label_before=pd.Timestamp.now(tz="UTC")
        )
        if frame is None or frame.empty:
            logger.info(f"Feature-store training skipped for {symbol}-{timeframe}: empty frame.")
            return None
        return frame

    async def _emit(self, event: Any) -> None:
        sink = self.alert_sink
        if sink is None:
            return
        try:
            await sink.send(event)
        except Exception as exc:
            logger.warning(f"Learning alert not delivered: {exc}")

    def _drift_within_cooldown(self, key: str) -> bool:
        last = self._drift_alert_at.get(key)
        if last is None:
            return False
        cooldown = self.settings.alert_drift_cooldown_hours * 3600.0
        return (self._clock() - last) < cooldown
