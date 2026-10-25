import asyncio
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

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

        if self.settings.drift_gate and not self._has_drift(data, timeframe):
            self._last_attempt[key] = self._clock()
            self._last_rows[key] = len(data)
            self.outcomes[key] = LearningOutcome(key=key, status="no_drift")
            logger.debug(f"Learning skipped for {key}: no feature drift")
            return

        self._last_attempt[key] = self._clock()

        baseline = self._baseline_metrics(model_type, symbol, timeframe)
        outcome = await self.model_manager.train_model(
            model_type,
            symbol,
            timeframe,
            data,
            promote=False,
            warm_start=True,
        )
        if outcome is None:
            self.outcomes[key] = LearningOutcome(key=key, status="failed")
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
            return

        self._rejections[key] = 0
        self.outcomes[key] = LearningOutcome(
            key=key, status="promoted", version=outcome.version, reasons=decision.reasons
        )
        logger.info(
            f"Promoted learned {model_type} version {outcome.version} for {symbol}-{timeframe}"
        )

    def _baseline_metrics(self, model_type: str, symbol: str, timeframe: str) -> dict[str, float]:
        try:
            metadata = self.model_manager.artifacts.read_metadata(model_type, symbol, timeframe)
        except (OSError, ValueError):
            return {}
        metrics = metadata.get("oos_metrics") if isinstance(metadata, dict) else None
        return metrics if isinstance(metrics, dict) else {}

    def _has_drift(self, data: pd.DataFrame, timeframe: str) -> bool:
        reference, live = split_windows(data, self.settings.live_window)
        if reference.empty or live.empty:
            return False
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
        return bool(summary.get("drifted"))

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
