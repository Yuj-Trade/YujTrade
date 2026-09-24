from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

from common.core import IndicatorResult
from common.exceptions import IndicatorError, ModelError, InsufficientDataError
from config.logger import logger
from config.settings import ConfigManager
from analysis.correlation import IndicatorCorrelationManager
from features.indicators.factory import IndicatorFactory


class FeatureEngineer:
    """مرز دو مسیر (شکاف ۹):
    - مسیر Signal: get_last_indicator_results() → AnalysisScorer (بدون scaler).
    - مسیر ML: create_features() → scale_features() → create_sequences() → Model.
    هر دو مسیر از یک primitive واحد (_compute_indicator) استفاده می‌کنند تا
    مدیریت متناقض ابزار واحد رخ ندهد. scaler و feature_columns فقط متعلق
    به مسیر ML هستند و مسیر Signal به آنها دست نمی‌زند."""

    def __init__(self, config_manager: ConfigManager = None):
        self.config_manager = config_manager if config_manager else ConfigManager()
        self.indicator_factory = IndicatorFactory()
        self.scaler = MinMaxScaler(feature_range=(0, 1))
        self.feature_columns: Optional[List[str]] = None
        self.correlation_manager = IndicatorCorrelationManager()

    def _compute_indicator(
        self, indicator_name: str, data: pd.DataFrame
    ) -> Optional[IndicatorResult]:
        """primitive واحد محاسبه اندیکاتور برای هر دو مسیر (Signal و ML)."""
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
        self, data: pd.DataFrame, indicators_to_run: List[str] = None
    ) -> pd.DataFrame:
        """
        Adds multiple indicator features to the dataframe.
        This method is kept for compatibility with model training but is less used in signal generation.
        """
        if indicators_to_run is None:
            # Use a default or broad set of indicators for feature creation
            indicators_to_run = list(self.indicator_factory.get_all_indicator_names())

        features_df = data.copy()

        for indicator_name in indicators_to_run:
            indicator_output = self._compute_indicator(indicator_name, features_df)
            if indicator_output is None:
                continue
            # For feature engineering, we care about the raw value
            value_to_add = None
            if isinstance(indicator_output.value, (pd.Series, np.ndarray)):
                value_to_add = indicator_output.value
            elif isinstance(indicator_output.value, (int, float, np.number)):
                # Create a series with the same index as the data to broadcast the single value
                value_to_add = pd.Series(
                    indicator_output.value, index=features_df.index
                )

            if value_to_add is not None:
                # Ensure the series is aligned with the dataframe index
                if not isinstance(
                    value_to_add.index, pd.DatetimeIndex
                ) or not value_to_add.index.equals(features_df.index):
                    value_to_add = pd.Series(
                        value_to_add.values,
                        index=features_df.index[-len(value_to_add) :],
                    )
                features_df[indicator_name] = value_to_add

        # Reorder columns to have original data first
        original_cols = ["open", "high", "low", "close", "volume"]
        indicator_cols = [
            col for col in features_df.columns if col not in original_cols
        ]

        # Ensure all original columns are present, even if they were not in the input
        for col in original_cols:
            if col not in features_df.columns:
                features_df[col] = np.nan

        features_df = features_df[original_cols + indicator_cols]
        features_df = features_df.dropna()

        # Keep track of feature columns created
        self.feature_columns = list(features_df.columns)
        return features_df

    def scale_features(
        self, features: pd.DataFrame, fit: bool = False
    ) -> Optional[np.ndarray]:
        if features.empty:
            return None
        if fit:
            self.scaler.fit(features)
            self.feature_columns = list(features.columns)

        # Avoid trying to scale if the scaler hasn't been fitted
        if not hasattr(self.scaler, "scale_"):
            logger.warning("Scaler has not been fitted. Cannot scale features.")
            return None

        return self.scaler.transform(features)

    def inverse_scale_prediction(self, prediction: np.ndarray) -> np.ndarray:
        if not hasattr(self.scaler, "scale_") or self.scaler.scale_ is None:
            raise ModelError("Scaler has not been fitted. Cannot inverse scale.")

        # Create a dummy array with the same number of features as the scaler was trained on
        num_features = self.scaler.n_features_in_
        dummy_array = np.zeros((len(prediction), num_features))

        # Find the index of the 'close' column
        try:
            if self.feature_columns is None:
                raise ValueError("feature_columns is not set.")
            close_idx = self.feature_columns.index("close")
        except ValueError:
            # Fallback to 0 if not found, assuming 'close' is the first column
            close_idx = 0
            logger.warning(
                "'close' column not found in feature columns. Assuming it is the first column for inverse scaling."
            )

        dummy_array[:, close_idx] = prediction.flatten()

        # Inverse transform the whole array
        inversed = self.scaler.inverse_transform(dummy_array)

        # Extract the inverse-transformed prediction
        return inversed[:, close_idx].reshape(-1, 1)

    def create_sequences(
        self, features: np.ndarray, target: np.ndarray, sequence_length: int
    ) -> Tuple[np.ndarray, np.ndarray]:
        X, y = [], []
        for i in range(len(features) - sequence_length):
            X.append(features[i : (i + sequence_length)])
            y.append(target[i + sequence_length])
        return np.array(X), np.array(y)

    def get_typical_volatility(self, timeframe: str) -> float:
        # Returns typical volatility percentage for a given timeframe
        volatility_map = {"1h": 0.01, "4h": 0.02, "1d": 0.04, "1w": 0.08, "1M": 0.15}
        return volatility_map.get(timeframe, 0.04)

    def get_last_indicator_results(
        self, data: pd.DataFrame, timeframe: str
    ) -> Dict[str, Any]:
        """
        Calculates and retrieves the last result for all active indicators for a given timeframe.
        This is the primary method used by the SignalGenerator (مسیر Signal).
        به scaler و feature_columns دست نمی‌زند (متعلق به مسیر ML).
        """
        results = {}
        active_indicators = self.config_manager.get_indicator_weights(timeframe).keys()

        for name in active_indicators:
            # Each indicator calculates its result based on the full data
            indicator_result = self._compute_indicator(name, data)
            if indicator_result is None or indicator_result.value is None:
                continue
            try:
                if bool(pd.isna(indicator_result.value).all() if isinstance(indicator_result.value, (pd.Series, np.ndarray)) else pd.isna(indicator_result.value)):
                    continue
            except (TypeError, ValueError):
                continue
            results[name] = {"result": indicator_result}

        # تصمیم شکاف ۷: همبستگی فقط با history واقعی؛ در مسیر زنده وزن خنثی.
        self.correlation_manager.compute_correlations(results)
        return results

    def get_decorrelation_weights(self, results: Dict[str, Any]) -> Dict[str, float]:
        """وزن‌های ضد‌همبستگی برای مسیر Signal؛ بدون history واقعی خنثی (1.0)."""
        return self.correlation_manager.get_decorrelation_weights(results)
