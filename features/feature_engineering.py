from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

from analysis.correlation import IndicatorCorrelationManager
from common.core import IndicatorResult
from common.exceptions import IndicatorError, InsufficientDataError, ModelError
from config.logger import logger
from config.settings import ConfigManager
from features.indicators.factory import IndicatorFactory


class FeatureEngineer:
    def __init__(self, config_manager: ConfigManager = None, history_provider=None):
        self.config_manager = config_manager if config_manager else ConfigManager()
        self.indicator_factory = IndicatorFactory()
        self.scaler = MinMaxScaler(feature_range=(0, 1))
        self.feature_columns: list[str] | None = None
        self.correlation_manager = IndicatorCorrelationManager()
        self.history_provider = history_provider

    def _compute_indicator(self, indicator_name: str, data: pd.DataFrame) -> IndicatorResult | None:
        indicator_instance = self.indicator_factory.create(indicator_name)
        if not indicator_instance:
            return None
        try:
            return indicator_instance.calculate(data)
        except (IndicatorError, InsufficientDataError) as e:
            logger.debug(f"Could not calculate indicator '{indicator_name}': {e}")
        except Exception as e:
            logger.error(
                f"Unexpected error with indicator '{indicator_name}': {e}",
                exc_info=True,
            )
        return None

    def create_features(
        self, data: pd.DataFrame, indicators_to_run: list[str] = None
    ) -> pd.DataFrame:
        if indicators_to_run is None:
            indicators_to_run = list(self.indicator_factory.get_all_indicator_names())

        features_df = data.copy()

        for indicator_name in indicators_to_run:
            indicator_output = self._compute_indicator(indicator_name, features_df)
            if indicator_output is None:
                continue

            value_to_add = None
            if isinstance(indicator_output.value, (pd.Series, np.ndarray)):
                value_to_add = indicator_output.value
            elif isinstance(indicator_output.value, (int, float, np.number)):
                value_to_add = pd.Series(indicator_output.value, index=features_df.index)

            if value_to_add is not None:
                if not isinstance(
                    value_to_add.index, pd.DatetimeIndex
                ) or not value_to_add.index.equals(features_df.index):
                    value_to_add = pd.Series(
                        value_to_add.values,
                        index=features_df.index[-len(value_to_add) :],
                    )
                features_df[indicator_name] = value_to_add

        original_cols = ["open", "high", "low", "close", "volume"]
        indicator_cols = [col for col in features_df.columns if col not in original_cols]

        for col in original_cols:
            if col not in features_df.columns:
                features_df[col] = np.nan

        features_df = features_df[original_cols + indicator_cols]
        features_df = features_df.dropna()

        self.feature_columns = list(features_df.columns)
        return features_df

    def scale_features(self, features: pd.DataFrame, fit: bool = False) -> np.ndarray | None:
        if features.empty:
            return None
        if fit:
            self.scaler.fit(features)
            self.feature_columns = list(features.columns)

        if not hasattr(self.scaler, "scale_"):
            logger.warning("Scaler has not been fitted. Cannot scale features.")
            return None

        return self.scaler.transform(features)

    def inverse_scale_prediction(self, prediction: np.ndarray) -> np.ndarray:
        if not hasattr(self.scaler, "scale_") or self.scaler.scale_ is None:
            raise ModelError("Scaler has not been fitted. Cannot inverse scale.")

        num_features = self.scaler.n_features_in_
        dummy_array = np.zeros((len(prediction), num_features))

        try:
            if self.feature_columns is None:
                raise ValueError("feature_columns is not set.")
            close_idx = self.feature_columns.index("close")
        except ValueError:
            close_idx = 0
            logger.warning(
                "'close' column not found in feature columns. "
                "Assuming it is the first column for inverse scaling."
            )

        dummy_array[:, close_idx] = prediction.flatten()

        inversed = self.scaler.inverse_transform(dummy_array)

        return inversed[:, close_idx].reshape(-1, 1)

    def create_sequences(
        self, features: np.ndarray, target: np.ndarray, sequence_length: int
    ) -> tuple[np.ndarray, np.ndarray]:
        X, y = [], []
        for i in range(len(features) - sequence_length):
            X.append(features[i : (i + sequence_length)])
            y.append(target[i + sequence_length])
        return np.array(X), np.array(y)

    def get_typical_volatility(self, timeframe: str) -> float:
        volatility_map = {"1h": 0.01, "4h": 0.02, "1d": 0.04, "1w": 0.08, "1M": 0.15}
        return volatility_map.get(timeframe, 0.04)

    async def get_last_indicator_results(
        self, data: pd.DataFrame, timeframe: str
    ) -> dict[str, Any]:
        results = {}
        active_indicators = self.config_manager.get_indicator_weights(timeframe).keys()

        for name in active_indicators:
            indicator_result = self._compute_indicator(name, data)
            if indicator_result is None or indicator_result.value is None:
                continue
            try:
                if bool(
                    pd.isna(indicator_result.value).all()
                    if isinstance(indicator_result.value, (pd.Series, np.ndarray))
                    else pd.isna(indicator_result.value)
                ):
                    continue
            except (TypeError, ValueError):
                continue
            results[name] = {"result": indicator_result}

        if self.history_provider is None:
            history = None
        elif hasattr(self.history_provider, "read"):
            history = await self.history_provider.read(results, 500)
        else:
            history = self.history_provider(list(results), 500)
        self.correlation_manager.compute_correlations(results, history)
        if self.history_provider is not None:
            timestamp = data.index[-1].isoformat()
            if hasattr(self.history_provider, "write_many"):
                await self.history_provider.write_many(
                    [
                        (name, timestamp, float(item["result"].value))
                        for name, item in results.items()
                    ]
                )
            elif hasattr(self.history_provider, "write"):
                for name, item in results.items():
                    value = item["result"].value
                    await self.history_provider.write(name, timestamp, float(value))
        return results

    def get_decorrelation_weights(self, results: dict[str, Any]) -> dict[str, float]:
        return self.correlation_manager.get_decorrelation_weights(results)
