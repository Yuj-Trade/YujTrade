import argparse
import asyncio
import json
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from common.constants import SYMBOLS, TIME_FRAMES
from config.logger import logger
from config.settings import ConfigManager
from data.data_provider import MarketDataProvider
from modeling.artifacts import ArtifactRegistry
from modeling.drift import (
    DEFAULT_DRIFT_FEATURES,
    build_drift_features,
    detect_feature_drift,
    drift_summary,
    split_windows,
)
from modeling.model_manager import ModelDataProvider, ModelManager
from modeling.promotion import PromotionPolicy, evaluate_promotion
from utils.resource_manager import ResourceManager

warnings.filterwarnings("ignore")

MODEL_TYPES = ("lstm", "xgboost")
DRIFT_CHECK_ONLY_EXIT_CODE = 2


class TrainingDataProvider(ModelDataProvider):
    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        config_manager: ConfigManager | None = None,
    ):
        self._market_data_provider = market_data_provider
        self._config_manager = config_manager or ConfigManager()

    async def get_data_for_model(
        self, symbol: str, timeframe: str, for_prediction: bool = False
    ) -> pd.DataFrame | None:
        limit_map = self._config_manager.get(
            "model_data_limits",
            {"1h": 2000, "4h": 1500, "1d": 1000, "1w": 500, "1M": 300},
        )
        limit = limit_map.get(timeframe, 2000)
        if for_prediction:
            limit = min(limit, self._config_manager.get("model_prediction_limit", 300))
        return await self._market_data_provider.fetch_ohlcv_data(symbol, timeframe, limit=limit)


class LocalCsvDataProvider(TrainingDataProvider):
    def __init__(self, frame: pd.DataFrame, config_manager: ConfigManager | None = None):
        super().__init__(None, config_manager)
        self._frame = frame

    async def fetch_ohlcv_data(
        self, symbol: str, timeframe: str, limit: int = 1000, bypass_cache: bool = False
    ) -> pd.DataFrame | None:
        return self._frame.tail(limit)

    async def get_data_for_model(
        self, symbol: str, timeframe: str, for_prediction: bool = False
    ) -> pd.DataFrame | None:
        limit_map = self._config_manager.get(
            "model_data_limits",
            {"1h": 2000, "4h": 1500, "1d": 1000, "1w": 500, "1M": 300},
        )
        limit = limit_map.get(timeframe, 2000)
        if for_prediction:
            limit = min(limit, self._config_manager.get("model_prediction_limit", 300))
        return self._frame.tail(limit)


def load_csv_ohlcv(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"OHLCV fixture is missing columns: {missing}")
    return frame


class ModelTrainer:
    def __init__(
        self,
        config: ConfigManager,
        market_data_provider: MarketDataProvider,
        model_manager: ModelManager,
        warm_start: bool = False,
        rollback_guard: bool = True,
        only_on_drift: bool = False,
    ):
        self.config = config
        self.market_data_provider = market_data_provider
        self.model_manager = model_manager
        self.warm_start = warm_start
        self.rollback_guard = rollback_guard
        self.only_on_drift = only_on_drift
        self.policy = PromotionPolicy.from_config(config)
        self.alpha = float(config.get("drift_alpha", 0.05))
        self.min_window = int(config.get("drift_min_window", 100))
        self.default_live_window = int(config.get("drift_live_window", 300))
        self.live_windows = dict(config.get("drift_live_windows", {}) or {})

    async def _fetch_data(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        limit_map = self.config.get(
            "model_data_limits",
            {"1h": 2000, "4h": 1500, "1d": 1000, "1w": 500, "1M": 300},
        )
        limit = limit_map.get(timeframe, 2000)
        return await self.market_data_provider.fetch_ohlcv_data(symbol, timeframe, limit=limit)

    def live_window_for(self, timeframe: str) -> int:
        return int(self.live_windows.get(timeframe, self.default_live_window))

    def evaluate_drift(self, data: pd.DataFrame, timeframe: str = "1h") -> dict[str, Any]:
        reference, live = split_windows(data, self.live_window_for(timeframe))
        reference_features = build_drift_features(reference)
        live_features = build_drift_features(live)
        reports = detect_feature_drift(
            reference_features,
            live_features,
            features=DEFAULT_DRIFT_FEATURES,
            alpha=self.alpha,
            min_window=self.min_window,
        )
        summary = drift_summary(reports, self.alpha, self.min_window)
        summary["live_window"] = self.live_window_for(timeframe)
        return summary

    def _baseline_metrics(self, symbol: str, timeframe: str, model_type: str) -> dict[str, float]:
        metadata = self.model_manager.artifacts.read_metadata(model_type, symbol, timeframe)
        if not metadata:
            return {}
        metrics = metadata.get("oos_metrics")
        return metrics if isinstance(metrics, dict) else {}

    async def train_and_save_model(
        self, symbol: str, timeframe: str, model_type: str
    ) -> dict[str, Any]:
        logger.info(f"--- Starting training for {symbol}-{timeframe} ({model_type}) ---")
        entry: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "model_type": model_type,
            "status": "skipped",
            "reason": "",
            "promoted": False,
            "version": None,
            "drift": None,
            "decision": None,
        }
        try:
            data = await self._fetch_data(symbol, timeframe)
            if data is None or data.empty or len(data) < 200:
                logger.warning(f"Insufficient data for {symbol}-{timeframe}. Skipping.")
                entry["reason"] = "insufficient_data"
                return entry

            drift = self.evaluate_drift(data, timeframe)
            entry["drift"] = drift
            if drift["drifted"]:
                logger.warning(
                    f"Feature drift detected for {symbol}-{timeframe}: {drift['drifted_features']}"
                )
            else:
                logger.info(
                    f"No feature drift detected for {symbol}-{timeframe} (alpha={self.alpha})"
                )

            if self.only_on_drift and not drift["drifted"]:
                entry["reason"] = "no_drift"
                return entry

            baseline = self._baseline_metrics(symbol, timeframe, model_type)
            outcome = await self.model_manager.train_model(
                model_type,
                symbol,
                timeframe,
                data,
                promote=False,
                warm_start=self.warm_start,
            )
            if outcome is None:
                logger.error(f"Failed to train model for {symbol}-{timeframe} ({model_type}).")
                entry["reason"] = "training_failed"
                return entry

            entry["version"] = outcome.version
            entry["oos_metrics"] = outcome.oos_metrics

            if not self.rollback_guard:
                logger.warning(
                    f"Rollback guard disabled; promoting {model_type} for {symbol}-{timeframe} "
                    "without degradation check"
                )
                try:
                    self.model_manager.artifacts.promote_version(
                        model_type, symbol, timeframe, outcome.version
                    )
                except (OSError, ValueError) as e:
                    entry["status"] = "error"
                    entry["reason"] = f"promotion_failed: {e}"
                    logger.error(
                        f"Promotion of {model_type} version {outcome.version} failed for "
                        f"{symbol}-{timeframe}: {e}"
                    )
                    return entry
                entry["promoted"] = True
                entry["status"] = "promoted"
                entry["reason"] = "guard_disabled"
                return entry

            decision = evaluate_promotion(baseline, outcome.oos_metrics, self.policy)
            entry["decision"] = decision.to_dict()
            if decision.promote:
                try:
                    self.model_manager.artifacts.promote_version(
                        model_type, symbol, timeframe, outcome.version
                    )
                except (OSError, ValueError) as e:
                    entry["status"] = "error"
                    entry["reason"] = f"promotion_failed: {e}"
                    logger.error(
                        f"Promotion of {model_type} version {outcome.version} failed for "
                        f"{symbol}-{timeframe}: {e}"
                    )
                    return entry
                entry["promoted"] = True
                entry["status"] = "promoted"
                entry["reason"] = decision.reasons[0]
                logger.info(
                    f"Promoted {model_type} version {outcome.version} for {symbol}-{timeframe}"
                )
            else:
                entry["status"] = "rejected"
                entry["reason"] = ",".join(decision.reasons)
                logger.warning(
                    f"Rejected {model_type} version {outcome.version} for {symbol}-{timeframe}; "
                    f"reasons={decision.reasons} baseline={baseline} "
                    f"candidate={outcome.oos_metrics}"
                )
            return entry
        except Exception as e:
            logger.opt(exception=True).error(
                f"Error during training for {symbol}-{timeframe} ({model_type}): {e}",
            )
            entry["status"] = "error"
            entry["reason"] = str(e)
            return entry

    async def dry_run(self, symbol: str, timeframe: str) -> dict[str, Any]:
        data = await self._fetch_data(symbol, timeframe)
        if data is None or data.empty or len(data) < 200:
            logger.warning(f"Insufficient data for drift check on {symbol}-{timeframe}.")
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "insufficient_data",
                "drift": None,
            }
        drift = self.evaluate_drift(data, timeframe)
        if drift["drifted"]:
            logger.warning(
                f"Feature drift detected for {symbol}-{timeframe}: {drift['drifted_features']}"
            )
        else:
            logger.info(f"No feature drift detected for {symbol}-{timeframe}")
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "drift" if drift["drifted"] else "stable",
            "drift": drift,
        }

    async def train_all_models(self) -> list[dict[str, Any]]:
        logger.info("Starting model training for all symbols and timeframes.")
        logger.info(
            "Legacy pickle scalers never load; every model trained here "
            "rewrites its scaler as validated JSON."
        )
        symbols: list[str] = self.config.get("symbols", SYMBOLS)
        timeframes: list[str] = self.config.get("timeframes", TIME_FRAMES)
        tasks = []
        if symbols and timeframes:
            for symbol in symbols:
                for timeframe in timeframes:
                    for model_type in MODEL_TYPES:
                        tasks.append(self.train_and_save_model(symbol, timeframe, model_type))

        results = await asyncio.gather(*tasks)
        logger.info("--- Model training process finished. ---")
        return list(results)

    async def dry_run_all(self) -> list[dict[str, Any]]:
        symbols: list[str] = self.config.get("symbols", SYMBOLS)
        timeframes: list[str] = self.config.get("timeframes", TIME_FRAMES)
        tasks = []
        for symbol in symbols:
            for timeframe in timeframes:
                tasks.append(self.dry_run(symbol, timeframe))
        results = await asyncio.gather(*tasks)
        return list(results)


def _resolve_targets(
    args: argparse.Namespace, config_manager: ConfigManager
) -> tuple[list[str], list[str]]:
    symbols = [args.symbol] if args.symbol else list(config_manager.get("symbols", SYMBOLS))
    timeframes = (
        [args.timeframe] if args.timeframe else list(config_manager.get("timeframes", TIME_FRAMES))
    )
    return symbols, timeframes


def _write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train YujTrade models with drift and rollback guards."
    )
    parser.add_argument("--dry-run", action="store_true", help="Drift check only; no training.")
    parser.add_argument(
        "--warm-start", action="store_true", help="Continue from the promoted artifact."
    )
    parser.add_argument(
        "--data", type=Path, default=None, help="Local OHLCV CSV instead of the network."
    )
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument(
        "--only-on-drift", action="store_true", help="Retrain only where drift is detected."
    )
    parser.add_argument(
        "--no-rollback-guard",
        action="store_true",
        help="Promote without the degradation check (operator override).",
    )
    parser.add_argument("--report", type=Path, default=None, help="Path of the JSON run report.")
    parser.add_argument("--artifact-root", type=Path, default=None)
    return parser


async def _run(args: argparse.Namespace) -> int:
    config_manager = ConfigManager()
    symbols, timeframes = _resolve_targets(args, config_manager)

    if args.data is not None:
        frame = load_csv_ohlcv(args.data)
        data_provider: Any = LocalCsvDataProvider(frame, config_manager)
        artifact_root = args.artifact_root or Path("artifacts")
        model_manager = ModelManager(
            data_provider=data_provider,
            model_path=str(artifact_root.parent / "models"),
        )
        model_manager.artifacts = ArtifactRegistry(artifact_root)
        trainer = ModelTrainer(
            config_manager,
            data_provider,
            model_manager,
            warm_start=args.warm_start,
            rollback_guard=not args.no_rollback_guard,
            only_on_drift=args.only_on_drift,
        )
        try:
            if args.dry_run:
                entries = []
                for symbol in symbols:
                    for timeframe in timeframes:
                        entries.append(await trainer.dry_run(symbol, timeframe))
                drifted = any(
                    bool(entry.get("drift")) and entry["drift"]["drifted"] for entry in entries
                )
                payload = {
                    "mode": "dry-run",
                    "data": str(args.data),
                    "entries": entries,
                    "drifted": drifted,
                }
                if args.report is not None:
                    _write_report(args.report, payload)
                return DRIFT_CHECK_ONLY_EXIT_CODE if drifted else 0
            results = []
            for symbol in symbols:
                for timeframe in timeframes:
                    for model_type in MODEL_TYPES:
                        results.append(
                            await trainer.train_and_save_model(symbol, timeframe, model_type)
                        )
            payload = {
                "mode": "train",
                "data": str(args.data),
                "entries": results,
                "promoted": sum(1 for entry in results if entry.get("promoted")),
            }
            if args.report is not None:
                _write_report(args.report, payload)
            return 0
        finally:
            await model_manager.shutdown()

    resource_manager = ResourceManager()
    await resource_manager.get_session()
    await resource_manager.get_redis_client()

    market_data_provider = MarketDataProvider(
        resource_manager=resource_manager, config_manager=config_manager
    )
    await market_data_provider.initialize()

    training_data_provider = TrainingDataProvider(market_data_provider, config_manager)

    model_manager = ModelManager(data_provider=training_data_provider, model_path="models")
    if args.artifact_root is not None:
        model_manager.artifacts = ArtifactRegistry(args.artifact_root)

    trainer = ModelTrainer(
        config_manager,
        market_data_provider,
        model_manager,
        warm_start=args.warm_start,
        rollback_guard=not args.no_rollback_guard,
        only_on_drift=args.only_on_drift,
    )
    try:
        if args.dry_run:
            entries = []
            for symbol in symbols:
                for timeframe in timeframes:
                    entries.append(await trainer.dry_run(symbol, timeframe))
            drifted = any(
                bool(entry.get("drift")) and entry["drift"]["drifted"] for entry in entries
            )
            payload = {
                "mode": "dry-run",
                "data": None,
                "entries": entries,
                "drifted": drifted,
            }
            if args.report is not None:
                _write_report(args.report, payload)
            return DRIFT_CHECK_ONLY_EXIT_CODE if drifted else 0
        results = await trainer.train_all_models()
        payload = {
            "mode": "train",
            "data": None,
            "entries": results,
            "promoted": sum(1 for entry in results if entry.get("promoted")),
        }
        if args.report is not None:
            _write_report(args.report, payload)
        return 0
    finally:
        await market_data_provider.close()
        await model_manager.shutdown()
        await resource_manager.cleanup()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except KeyboardInterrupt:
        logger.info("Training process interrupted by user.")
        exit_code = 0
    except Exception as e:
        logger.opt(exception=True).error(f"Fatal error in training script: {e}")
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
