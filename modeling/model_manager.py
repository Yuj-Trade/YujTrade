import asyncio
import os
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

import numpy as np
import pandas as pd
import redis

from common import metrics
from common.exceptions import ArtifactIntegrityError, ObjectClosedError
from config.logger import logger
from modeling.artifacts import ArtifactRegistry, build_metadata
from modeling.models import BaseModel, LSTMModel, XGBoostModel

LABEL_HORIZON = 1
OOS_FRACTION = 0.2


@dataclass(frozen=True)
class TrainingOutcome:
    model_type: str
    symbol: str
    timeframe: str
    version: str
    promoted: bool
    oos_metrics: dict[str, float]
    artifact_path: str


def compute_oos_metrics(model: BaseModel, data: Any) -> dict[str, float]:
    closes = data["close"].to_numpy(dtype=float)
    split = max(1, int(len(data) * (1 - OOS_FRACTION)))
    preds: list[float] = []
    actuals: list[float] = []
    previous_closes: list[float] = []
    for end in range(split + LABEL_HORIZON, len(data) - 1):
        result = model.predict(data.iloc[: end + 1])
        if not result:
            continue
        prediction = result[0]
        preds.append(float(prediction.ravel()[0]))
        actuals.append(float(closes[end + 1]))
        previous_closes.append(float(closes[end]))
    if not preds:
        return {"rmse": float("nan"), "directional_accuracy": float("nan")}
    errors = [p - a for p, a in zip(preds, actuals, strict=False)]
    rmse = float((sum(e * e for e in errors) / len(errors)) ** 0.5)
    hits = sum(
        1
        for pred, actual, previous in zip(preds, actuals, previous_closes, strict=False)
        if (pred > previous) == (actual > previous)
    )
    return {"rmse": rmse, "directional_accuracy": hits / len(preds)}


def _model_params(model_type: str, model: BaseModel) -> dict[str, Any]:
    if model_type == "lstm":
        return {
            "units": getattr(model, "units", None),
            "lr": getattr(model, "lr", None),
            "sequence_length": getattr(model, "sequence_length", None),
            "batch_size": getattr(model, "batch_size", None),
        }
    params = getattr(model, "params", None)
    return dict(params) if isinstance(params, dict) else {}


class ModelDataProvider(Protocol):
    async def get_data_for_model(
        self, symbol: str, timeframe: str, for_prediction: bool = False
    ) -> pd.DataFrame | None: ...


class ModelManager:
    def __init__(
        self,
        data_provider: ModelDataProvider,
        model_path: str = "models",
        redis_client: redis.Redis | None = None,
        auto_train_on_predict: bool = False,
    ):
        self.model_path = Path(model_path)
        self.model_path.mkdir(parents=True, exist_ok=True)
        self.redis_client = redis_client

        self.auto_train_on_predict = auto_train_on_predict
        self._cache: dict[str, BaseModel] = {}
        self._lock = asyncio.Lock()
        self._is_closed = False
        self.logger = logger
        self._training_executor = None
        self._prediction_executor = None
        self.data_provider = data_provider
        self.artifacts = ArtifactRegistry(self.model_path.parent / "artifacts")

    def _check_if_closed(self):
        if self._is_closed:
            raise ObjectClosedError("ModelManager has been closed and cannot be used")

    async def _get_executor(self, executor_type: str) -> ThreadPoolExecutor:
        self._check_if_closed()

        if executor_type == "training":
            if self._training_executor is None or self._training_executor._shutdown:
                max_workers = max(1, (os.cpu_count() or 4) // 2)
                self._training_executor = ThreadPoolExecutor(
                    max_workers=max_workers, thread_name_prefix="ModelTrainingExecutor"
                )
            return self._training_executor
        elif executor_type == "prediction":
            if self._prediction_executor is None or self._prediction_executor._shutdown:
                max_workers = max(1, (os.cpu_count() or 2))
                self._prediction_executor = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="ModelPredictionExecutor",
                )
            return self._prediction_executor
        else:
            raise ValueError("Invalid executor type specified.")

    async def _run_in_executor(
        self, func, *args, executor_type: str = "prediction", **kwargs
    ) -> Any:
        self._check_if_closed()
        loop = asyncio.get_running_loop()
        executor = await self._get_executor(executor_type)
        return await loop.run_in_executor(executor, lambda: func(*args, **kwargs))

    def _get_model_class(self, model_type: str) -> type["BaseModel"]:
        if model_type == "lstm":
            return LSTMModel
        if model_type == "xgboost":
            return XGBoostModel
        raise ValueError(f"Unknown model type: {model_type}")

    async def get_model(
        self, model_type: str, symbol: str, timeframe: str, auto_load: bool = True
    ) -> Optional["BaseModel"]:
        self._check_if_closed()
        key = f"{model_type}-{symbol}-{timeframe}"

        async with self._lock:
            if key in self._cache:
                cached_model = self._cache[key]
                if not cached_model._is_closed:
                    return cached_model
                del self._cache[key]

        model_dir = self.model_path / model_type
        model_class = self._get_model_class(model_type)
        artifact_dir = self.artifacts.current_dir(model_type, symbol, timeframe)
        if artifact_dir is not None:
            model_dir = artifact_dir
        model_path_str = str(model_dir)

        try:
            model = await self._run_in_executor(
                lambda: model_class(symbol=symbol, timeframe=timeframe, model_path=model_path_str),
                executor_type="prediction",
            )

            if auto_load:
                model_name_map = {"lstm": "keras", "xgboost": "json"}
                model_ext = model_name_map.get(model_type)
                if model_ext:
                    model_file, scaler_file = model._get_model_paths(model_type, model_ext)

                    if model_file.exists() and scaler_file.exists():
                        try:
                            self.artifacts.verify_current(model_type, symbol, timeframe)
                            await self._run_in_executor(model.load, executor_type="prediction")
                            samples = self.artifacts.load_calibration(model_type, symbol, timeframe)
                            if samples:
                                model.calibrator.calibration_data[
                                    f"{model_type}_{symbol}_{timeframe}"
                                ] = samples
                            self.logger.info(
                                f"Loaded existing {model_type.upper()} model for {key}"
                            )
                        except ArtifactIntegrityError as e:
                            metrics.record_artifact_mismatch()
                            self.logger.warning(
                                f"model_unavailable: integrity check failed for "
                                f"{model_type.upper()} model for {key}: {e}"
                            )
                            model.is_trained = False
                        except Exception as e:
                            self.logger.warning(
                                f"Failed to load {model_type.upper()} model for {key}: {e}"
                            )
                            model.is_trained = False
                    else:
                        self.logger.info(
                            f"No existing {model_type.upper()} model found "
                            f"for {key}, needs training"
                        )
                        model.is_trained = False
                else:
                    model.is_trained = False

            async with self._lock:
                if key not in self._cache:
                    self._cache[key] = model
                else:
                    model.cleanup()
                    return self._cache[key]
            return model
        except Exception as e:
            self.logger.opt(exception=True).error(
                f"Could not get or create {model_type.upper()} model for {key}: {e}",
            )
            return None

    async def train_model(
        self,
        model_type: str,
        symbol: str,
        timeframe: str,
        data: pd.DataFrame,
        promote: bool = True,
        warm_start: bool = False,
        feature_frame: pd.DataFrame | None = None,
        **kwargs,
    ) -> TrainingOutcome | None:
        self._check_if_closed()

        if data is None or data.empty:
            self.logger.warning(f"Cannot train {model_type} for {symbol}-{timeframe}: empty data")
            return None

        model = await self.get_model(model_type, symbol, timeframe, auto_load=bool(warm_start))
        if not model:
            self.logger.error(f"Failed to create model {model_type} for {symbol}-{timeframe}")
            return None

        model.model_path = self.model_path / model_type

        effective_warm_start = bool(warm_start) and bool(model.is_trained)
        if warm_start and not effective_warm_start:
            self.logger.warning(
                f"Warm start unavailable for {model_type} on {symbol}-{timeframe}; "
                "training from cold initialization"
            )

        try:
            success = await self._run_in_executor(
                model.fit,
                data,
                executor_type="training",
                warm_start=effective_warm_start,
                feature_frame=feature_frame,
                **kwargs,
            )
            if success:
                model_file, scaler_file = model._get_model_paths(
                    model_type, "keras" if model_type == "lstm" else "json"
                )
                feature_frame = await self._run_in_executor(
                    model.feature_engineer.create_features,
                    data,
                    executor_type="training",
                )
                oos_metrics = await self._run_in_executor(
                    compute_oos_metrics, model, data, executor_type="training"
                )
                metadata = build_metadata(
                    data,
                    list(feature_frame.columns),
                    _model_params(model_type, model),
                    oos_metrics,
                    source_files=[model_file, scaler_file],
                )
                version_dir = self.artifacts.create_version(
                    model_type,
                    symbol,
                    timeframe,
                    [model_file, scaler_file],
                    metadata=metadata,
                    update_current=promote,
                )
                self.logger.info(
                    f"Successfully trained {model_type.upper()} model for {symbol}-{timeframe}"
                )
                async with self._lock:
                    key = f"{model_type}-{symbol}-{timeframe}"
                    if promote:
                        existing = self._cache.get(key)
                        if existing is not None and existing is not model:
                            existing.cleanup()
                        self._cache[key] = model
                    else:
                        self._cache.pop(key, None)
                if not promote:
                    model.cleanup()
                return TrainingOutcome(
                    model_type=model_type,
                    symbol=symbol,
                    timeframe=timeframe,
                    version=version_dir.name,
                    promoted=promote,
                    oos_metrics={name: float(value) for name, value in dict(oos_metrics).items()},
                    artifact_path=str(version_dir),
                )
            else:
                self.logger.warning(
                    f"Training failed for {model_type.upper()} model {symbol}-{timeframe}"
                )
                return None
        except Exception as e:
            self.logger.opt(exception=True).error(
                f"Error training {model_type.upper()} model for {symbol}-{timeframe}: {e}",
            )
            return None

    async def initialize_all_models(self):
        self._check_if_closed()
        self.logger.info("Initializing all models (LSTM, XGBoost)...")
        tasks = []
        model_files = []

        for model_type_dir in self.model_path.iterdir():
            if not model_type_dir.is_dir():
                continue

            model_type = model_type_dir.name
            if model_type == "lstm":
                ext = "keras"
            elif model_type == "xgboost":
                ext = "json"
            else:
                continue

            for file in model_type_dir.glob(f"*.{ext}"):
                model_files.append((file, model_type))

        for file, model_type in model_files:
            try:
                base_name = file.stem
                if model_type == "lstm":
                    parts_str = base_name.replace("lstm_", "")
                elif model_type == "xgboost":
                    parts_str = base_name.replace("xgboost_", "")
                else:
                    continue

                symbol, timeframe = parts_str.rsplit("_", 1)
                symbol_formatted = symbol.upper()
                if "/" not in symbol_formatted and len(symbol_formatted) > 4:
                    if "USDT" in symbol_formatted:
                        symbol_formatted = symbol_formatted.replace("USDT", "/USDT", 1)
                    elif "BUSD" in symbol_formatted:
                        symbol_formatted = symbol_formatted.replace("BUSD", "/BUSD", 1)

                tasks.append(self.get_model(model_type, symbol_formatted, timeframe))
            except (IndexError, ValueError) as e:
                self.logger.warning(f"Could not parse model file name: {file.name}. Error: {e}")

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                self.logger.opt(exception=res).error(f"Error during model initialization: {res}")
        self.logger.info(f"Model initialization finished. Loaded/Created {len(tasks)} models.")

    async def train_and_save_model(self, model_type: str, symbol: str, timeframe: str) -> bool:
        self.logger.info(
            f"Attempting to train and save {model_type} model for {symbol}-{timeframe}"
        )
        data = await self.data_provider.get_data_for_model(symbol, timeframe)
        if data is None or data.empty:
            self.logger.warning(
                f"Could not fetch sufficient data for model training: {symbol}-{timeframe}"
            )
            return False

        outcome = await self.train_model(model_type, symbol, timeframe, data)
        return outcome is not None

    async def predict_with_confidence(
        self, model_type: str, symbol: str, timeframe: str
    ) -> dict[str, float] | None:
        self._check_if_closed()

        model = await self.get_model(model_type, symbol, timeframe)
        if not model:
            self.logger.warning(
                f"model_unavailable: no artifact for {model_type} on {symbol}-{timeframe}"
            )
            return None

        if not model.is_trained:
            if not self.auto_train_on_predict:
                self.logger.info(
                    f"model_unavailable: {model_type} for {symbol}-{timeframe} is not trained"
                )
                return None
            self.logger.info(
                f"Model {model_type} for {symbol}-{timeframe} is not trained. "
                "Attempting to train now."
            )
            success = await self.train_and_save_model(model_type, symbol, timeframe)
            if not success:
                self.logger.warning(
                    f"Training failed for {model_type} on {symbol}-{timeframe}. "
                    "Skipping prediction."
                )
                return None

            model = await self.get_model(model_type, symbol, timeframe)
            if not model or not model.is_trained:
                self.logger.error(
                    f"Model still not trained after attempt "
                    f"for {model_type} on {symbol}-{timeframe}."
                )
                return None

        data = await self.data_provider.get_data_for_model(symbol, timeframe, for_prediction=True)
        if data is None or data.empty:
            self.logger.warning(
                f"model_unavailable: empty data for prediction {model_type} on {symbol}-{timeframe}"
            )
            return None

        try:
            prediction_result = await self._run_in_executor(
                model.predict, data, executor_type="prediction"
            )
            if prediction_result is None or len(prediction_result) != 2:
                self.logger.warning(
                    f"model_unavailable: invalid prediction result for {model_type} "
                    f"on {symbol}-{timeframe}"
                )
                return None

            prediction, uncertainty = prediction_result
            if (
                prediction is None
                or len(prediction) == 0
                or np.isnan(prediction[0])
                or np.isinf(prediction[0])
            ):
                self.logger.warning(
                    f"model_unavailable: invalid prediction for {model_type} "
                    f"on {symbol}-{timeframe}"
                )
                return None

            current_price = data["close"].iloc[-1]
            raw_confidence = 0.0
            if current_price > 0:
                expected_pct_change = model.feature_engineer.get_typical_volatility(timeframe) * 100
                if expected_pct_change > 0:
                    price_change_pct = abs(prediction[0] - current_price) / current_price * 100

                    raw_confidence = np.clip(
                        100
                        - (abs(price_change_pct - expected_pct_change) / expected_pct_change) * 100,
                        30,
                        95,
                    )
                else:
                    raw_confidence = 50.0

            model_name = f"{model_type}_{symbol}_{timeframe}"
            calibrated_confidence = model.calibrator.get_calibrated_confidence(
                model_name, raw_confidence
            )

            final_confidence = max(0.0, min(100.0, calibrated_confidence * (1 - uncertainty**2)))

            return {
                "prediction": float(prediction[0]),
                "confidence": final_confidence,
                "raw_confidence": raw_confidence,
                "calibrated_confidence": calibrated_confidence,
                "uncertainty": uncertainty,
                "feature_vector": _model_input_vector(model, data, prediction_result),
                "candle_time": data.index[-1],
            }
        except (ObjectClosedError, CancelledError) as e:
            self.logger.warning(
                f"Prediction task cancelled or failed for {model_type} on {symbol}-{timeframe}: {e}"
            )
            return None
        except Exception as e:
            self.logger.opt(exception=True).error(
                f"Prediction failed for {model_type} on {symbol}-{timeframe}: {e}",
            )
            return None

    async def record_signal_performance(
        self,
        model_type: str,
        symbol: str,
        timeframe: str,
        confidence: float,
        success: bool,
    ):
        self._check_if_closed()
        model = await self.get_model(model_type, symbol, timeframe)
        if model and model.calibrator:
            model_name = f"{model_type}_{symbol}_{timeframe}"
            model.calibrator.add_prediction(model_name, confidence, success)
            self.artifacts.save_calibration(
                model_type,
                symbol,
                timeframe,
                model.calibrator.calibration_data.get(model_name, []),
            )

    async def shutdown(self):
        if self._is_closed:
            return

        self._is_closed = True
        self.logger.info("Shutting down ModelManager...")

        async with self._lock:
            models_to_clean = list(self._cache.values())
            self._cache.clear()

        for model in models_to_clean:
            try:
                model.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up model {model.symbol}-{model.timeframe}: {e}")

        for executor_attr in ["_training_executor", "_prediction_executor"]:
            if hasattr(self, executor_attr):
                executor = getattr(self, executor_attr)
                if executor:
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except Exception as e:
                        self.logger.error(f"Error shutting down executor: {e}")

        self.logger.info("ModelManager shut down.")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()


def _model_input_vector(model: Any, data: Any, prediction_result: Any) -> dict[str, float] | None:
    try:
        features = model.feature_engineer.create_features(data)
        if features is None or features.empty:
            return None
        last = features.tail(1).iloc[0]
        return {str(name): float(value) for name, value in last.items()}
    except Exception:
        return None
